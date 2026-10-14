from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.constants import PERMANENT_THREAD_MUTE
from StellariaPact.cogs.Punishment.dto import PunishmentRecordDto, ThreadPunishmentHistoryDto
from StellariaPact.cogs.Punishment.PunishmentCog import PunishmentCog
from StellariaPact.cogs.Punishment.qo import (
    ApplyThreadPunishmentQo,
    LiftThreadPunishmentQo,
    QueryThreadPunishmentQo,
    SavePunishmentPanelQo,
)
from StellariaPact.cogs.Punishment.views.OffTopicConfirmationModal import OffTopicConfirmationModal
from StellariaPact.cogs.Punishment.views.PunishmentEmbedBuilder import PunishmentEmbedBuilder
from StellariaPact.cogs.Punishment.views.PunishmentHistoryModal import PunishmentHistoryModal
from StellariaPact.cogs.StructuredSpeech.StructuredSpeechCog import StructuredSpeechCog
from StellariaPact.share.auth.RoleGuard import RoleGuard


async def submit(coroutine, priority):
    return await coroutine


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    bot = MagicMock()
    bot.user.id = 999
    bot.db_handler = SimpleNamespace(get_session=lambda: AsyncSession(engine))
    bot.api_scheduler.submit.side_effect = submit
    guild = MagicMock(id=1)
    thread = MagicMock(spec=discord.Thread, id=10, guild=guild)
    thread.send = AsyncMock(return_value=MagicMock(id=202))
    target = MagicMock(spec=discord.Member, id=20, bot=False, mention="<@20>")
    moderator = MagicMock(spec=discord.Member, id=30, mention="<@30>")
    guild.get_channel_or_thread.return_value = thread
    guild.get_member.return_value = target
    interaction = MagicMock(
        spec=discord.Interaction,
        user=moderator,
        guild=guild,
        guild_id=1,
        channel=thread,
        channel_id=10,
    )
    interaction.response.send_modal = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    cog = PunishmentCog(bot)
    cog.publicity_service.resolve_channel = AsyncMock(
        return_value=SimpleNamespace(channel=None, fallback_reason="未配置公示区")
    )
    yield SimpleNamespace(
        cog=cog,
        bot=bot,
        thread=thread,
        target=target,
        moderator=moderator,
        interaction=interaction,
    )
    await engine.dispose()


async def punish(context):
    return await context.cog.logic.apply_thread_punishment(
        ApplyThreadPunishmentQo(
            guild_id=1,
            thread_id=10,
            target_user_id=20,
            moderator_id=30,
            reason="",
            source_message_url=None,
            voting_allowed=True,
            mute_end_time=None,
            quick_mode="cumulative",
        )
    )


def panel_message(context, kind):
    channel = context.thread if kind != "formal" else MagicMock(id=99)
    return MagicMock(
        spec=discord.Message,
        id=201 if kind == "formal" else 202,
        author=context.bot.user,
        channel=channel,
        webhook_id=None,
        embeds=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["formal", "source", "legacy"])
async def test_registered_panels_locate_original_thread_and_target(context, kind):
    result = await punish(context)
    await context.cog.logic.save_publicity_panel(
        SavePunishmentPanelQo(
            record_id=result.punishment_record_id, guild_id=1, channel_id=99, message_id=201
        )
    )
    message = panel_message(context, kind)
    if kind == "source":
        await context.cog.logic.save_publicity_panel(
            SavePunishmentPanelQo(
                record_id=result.punishment_record_id,
                guild_id=1,
                channel_id=10,
                message_id=202,
                is_source=True,
            )
        )
    elif kind == "legacy":
        embed = discord.Embed(title="议事成员资格及处罚变动公示")
        embed.add_field(name="处罚公示", value="[点击跳转](https://discord.com/channels/1/99/201)")
        message.embeds = [embed]
    context.interaction.channel = message.channel
    context.interaction.channel_id = message.channel.id
    await context.cog.remove_punishment_message.__wrapped__(
        context.cog, context.interaction, message
    )
    modal = context.interaction.response.send_modal.await_args.args[0]
    assert modal.thread is context.thread
    assert modal.target_user is context.target
    assert modal.expected_record_id == result.punishment_record_id
    assert len(modal.children) == 3
    assert "当前累计处罚：**1 次**" in modal.children[0].content
    modal.reason._value = "复核后解除"
    with (
        patch.object(RoleGuard, "hasRoles", return_value=True),
        patch("StellariaPact.cogs.Punishment.PunishmentCog.safeDefer", new=AsyncMock()),
    ):
        await modal.on_submit(context.interaction)
    assert (
        await context.cog.logic.get_thread_history(
            QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
        )
    ).cumulative_count == 0
    assert "处罚已解除" in context.interaction.followup.send.await_args.args[0]
    context.thread.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_and_lifted_panels_are_rejected(context):
    first = await punish(context)
    await context.cog.logic.save_publicity_panel(
        SavePunishmentPanelQo(
            record_id=first.punishment_record_id,
            guild_id=1,
            channel_id=10,
            message_id=202,
            is_source=True,
        )
    )
    latest = await punish(context)
    await context.cog.remove_punishment_message.__wrapped__(
        context.cog, context.interaction, panel_message(context, "source")
    )
    context.interaction.response.send_modal.assert_not_awaited()
    assert "后续处罚覆盖" in context.interaction.response.send_message.await_args.args[0]
    await context.cog.logic.save_publicity_panel(
        SavePunishmentPanelQo(
            record_id=latest.punishment_record_id,
            guild_id=1,
            channel_id=10,
            message_id=203,
            is_source=True,
        )
    )
    await context.cog.logic.lift_thread_punishment(
        LiftThreadPunishmentQo(
            thread_id=10,
            target_user_id=20,
            expected_record_id=latest.punishment_record_id,
            moderator_id=30,
            reason="解除",
        )
    )
    latest_panel = panel_message(context, "source")
    latest_panel.id = 203
    await context.cog.remove_punishment_message.__wrapped__(
        context.cog, context.interaction, latest_panel
    )
    assert "已经解除" in context.interaction.response.send_message.await_args.args[0]


@pytest.mark.asyncio
async def test_unknown_bot_panels_do_not_infer_target_from_mentions(context):
    await punish(context)
    message = panel_message(context, "source")
    message.embeds = [discord.Embed(description="**目标用户**: <@20>")]
    await context.cog.remove_punishment_message.__wrapped__(
        context.cog, context.interaction, message
    )
    assert "无法可靠关联" in context.interaction.response.send_message.await_args.args[0]
    context.interaction.response.send_modal.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_punishment", "lost_permission"])
async def test_removal_modal_rechecks_state_and_permission_at_submission(context, change):
    first = await punish(context)
    await context.cog.logic.save_publicity_panel(
        SavePunishmentPanelQo(
            record_id=first.punishment_record_id,
            guild_id=1,
            channel_id=10,
            message_id=202,
            is_source=True,
        )
    )
    await context.cog.remove_punishment_message.__wrapped__(
        context.cog, context.interaction, panel_message(context, "source")
    )
    modal = context.interaction.response.send_modal.await_args.args[0]
    modal.reason._value = "复核解除"
    if change == "new_punishment":
        await punish(context)
    with (
        patch.object(RoleGuard, "hasRoles", return_value=change != "lost_permission"),
        patch("StellariaPact.cogs.Punishment.PunishmentCog.safeDefer", new=AsyncMock()),
    ):
        await modal.on_submit(context.interaction)
    if change == "new_punishment":
        assert "后续处罚覆盖" in context.interaction.followup.send.await_args.args[0]
        assert (
            await context.cog.logic.get_thread_history(
                QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
            )
        ).cumulative_count == 2
    else:
        assert "没有解除处罚的权限" in context.interaction.response.send_message.await_args.args[0]
        assert (
            await context.cog.logic.get_thread_history(
                QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
            )
        ).cumulative_count == 1
    context.thread.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["yes", "no"])
async def test_off_topic_modal_defaults_yes_and_recomputes_count_on_no(context, choice):
    await punish(context)
    message = MagicMock(
        spec=discord.Message, channel=context.thread, jump_url="https://discord.com/1"
    )
    context.cog._resolve_message_target = AsyncMock(return_value=context.target)
    await context.cog.quick_punish_off_topic_message.__wrapped__(
        context.cog, context.interaction, message
    )
    modal = context.interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, OffTopicConfirmationModal)
    assert modal.choice.options[0].value == "yes" and modal.choice.options[0].default
    assert "1 次累计处罚" in modal.children[0].content
    assert (
        await context.cog.logic.get_thread_history(
            QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
        )
    ).cumulative_count == 1
    await punish(context)
    modal.choice._values = [choice]
    with (
        patch.object(RoleGuard, "hasRoles", return_value=True),
        patch("StellariaPact.cogs.Punishment.PunishmentCog.safeDefer", new=AsyncMock()),
    ):
        await modal.on_submit(context.interaction)
    assert (
        await context.cog.logic.get_thread_history(
            QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
        )
    ).cumulative_count == (3 if choice == "no" else 2)
    embed = context.thread.send.await_args.kwargs["embed"]
    assert embed.fields[0].value == (
        "请不要歪楼滑坡，三次处罚" if choice == "no" else "请不要歪楼滑坡"
    )


@pytest.mark.asyncio
async def test_confirmation_submit_checks_revoked_permissions(context):
    message = MagicMock(spec=discord.Message, channel=context.thread)
    modal = OffTopicConfirmationModal(context.cog, context.target, message, 1)
    with patch.object(RoleGuard, "hasRoles", return_value=False):
        await modal.on_submit(context.interaction)
    assert "没有执行处罚的权限" in context.interaction.response.send_message.await_args.args[0]
    assert (
        await context.cog.logic.get_thread_history(
            QueryThreadPunishmentQo(thread_id=10, target_user_id=20)
        )
    ).cumulative_count == 0


@pytest.mark.asyncio
async def test_registration_and_unloading_respect_menu_limits(context):
    from discord import app_commands

    client = MagicMock()
    client._connection._command_tree = None
    tree = app_commands.CommandTree(client)
    context.bot.tree = tree
    speech = StructuredSpeechCog(context.bot)
    context.cog.cog_load()
    speech.cog_load()
    assert len(tree.get_commands(type=discord.AppCommandType.message)) == 5
    assert {command.name for command in tree.get_commands(type=discord.AppCommandType.user)} == {
        "查询提案内处罚记录",
        "查看全局提案处罚",
    }
    await context.cog.cog_unload()
    await speech.cog_unload()
    assert not tree.get_commands(type=discord.AppCommandType.message)
    assert not tree.get_commands(type=discord.AppCommandType.user)


@pytest.mark.asyncio
async def test_permanent_embeds_and_history_do_not_render_extreme_dates(context):
    result = None
    for _ in range(4):
        result = await punish(context)
    embed = PunishmentEmbedBuilder.create_punishment_embed(
        context.moderator, context.target, result.reason, None, True, PERMANENT_THREAD_MUTE
    )
    assert "永久禁言" in embed.description
    assert "253402" not in embed.description
    async with context.bot.db_handler.get_session() as session:
        from StellariaPact.repository.PunishmentRecordRepository import PunishmentRecordRepository

        total, records = await PunishmentRecordRepository(session).get_summary(
            thread_id=10, target_user_id=20
        )
    modal = PunishmentHistoryModal(
        context.target,
        ThreadPunishmentHistoryDto(
            total,
            4,
            PunishmentRecordDto.model_validate(records[0]),
            [PunishmentRecordDto.model_validate(record) for record in records],
        ),
    )
    assert "永久禁言" in modal.children[1].content
