from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.StructuredSpeech.StructuredSpeechService import (
    StructuredSpeechService,
)
from StellariaPact.cogs.StructuredSpeech.StructuredSpeechUserError import (
    StructuredSpeechUserError,
)
from StellariaPact.dto.structured_speech import StructuredSpeechModeDto
from StellariaPact.models.StructuredSpeechMessage import StructuredSpeechMessage
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.qo.structured_speech import (
    DeleteStructuredSpeechMessagesQo,
    DisableStructuredSpeechModeQo,
    EnableStructuredSpeechModeQo,
    PublishStructuredSpeechQo,
    ResolveStructuredSpeechReferenceQo,
)


def _create_bot(engine: AsyncEngine) -> MagicMock:
    """创建使用内存数据库和即时 API 调度器的测试 Bot。"""
    database_handler = MagicMock()
    database_handler.get_session.side_effect = lambda: AsyncSession(engine)

    async def submit(coroutine, priority):
        """直接等待测试中的 Discord 协程。"""
        del priority
        return await coroutine

    bot = MagicMock()
    bot.db_handler = database_handler
    bot.api_scheduler.submit.side_effect = submit
    return bot


@pytest_asyncio.fixture
async def structured_engine():
    """提供包含完整 SQLModel 元数据的内存数据库。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_external_slowmode_change_is_not_corrected_but_disable_restores_original(
    structured_engine: AsyncEngine,
) -> None:
    """验证活动期间不纠正外部修改，而关闭时始终恢复开启前数值。"""
    bot = _create_bot(structured_engine)
    service = StructuredSpeechService(bot)
    parent = MagicMock(id=20)
    thread = MagicMock(id=30, slowmode_delay=15)
    thread.parent = parent
    thread.guild = SimpleNamespace(id=10)
    thread.edit = AsyncMock(return_value=thread)

    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.ForumChannel",
        type(parent),
    ):
        enabled = await service.enable_mode(
            thread=thread,
            qo=EnableStructuredSpeechModeQo(operator_id=40),
        )
        thread.slowmode_delay = 42
        updated = await service.enable_mode(
            thread=thread,
            qo=EnableStructuredSpeechModeQo(operator_id=40, interval_seconds=300),
        )
        disabled = await service.disable_mode(
            thread,
            DisableStructuredSpeechModeQo(operator_id=40),
        )

    assert enabled.action == "enabled"
    assert updated.action == "updated"
    assert disabled.action == "disabled"
    assert thread.edit.await_args_list == [
        call(slowmode_delay=600, reason="切换提案讨论模板发言模式"),
        call(slowmode_delay=15, reason="切换提案讨论模板发言模式"),
    ]


@pytest.mark.asyncio
async def test_active_mode_load_does_not_read_or_change_discord_slowmode(
    structured_engine: AsyncEngine,
) -> None:
    """验证重启加载活动态时不会读取帖子并重设慢速模式。"""
    bot = _create_bot(structured_engine)
    first_service = StructuredSpeechService(bot)
    parent = MagicMock(id=20)
    thread = MagicMock(id=30, slowmode_delay=15)
    thread.parent = parent
    thread.guild = SimpleNamespace(id=10)
    thread.edit = AsyncMock(return_value=thread)

    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.ForumChannel",
        type(parent),
    ):
        await first_service.enable_mode(
            thread=thread,
            qo=EnableStructuredSpeechModeQo(operator_id=40),
        )

    reloaded_service = StructuredSpeechService(bot)
    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.DiscordUtils.fetch_thread",
        new=AsyncMock(),
    ) as fetch_thread:
        await reloaded_service.load_and_recover()

    fetch_thread.assert_not_awaited()
    assert reloaded_service.get_active_mode(thread.id) is not None


@pytest.mark.asyncio
async def test_reference_user_resolution_supports_members_and_tracked_webhooks(
    structured_engine: AsyncEngine,
) -> None:
    """验证普通成员直接解析，结构化 Webhook 从消息元数据还原原用户。"""
    bot = _create_bot(structured_engine)
    service = StructuredSpeechService(bot)
    async with AsyncSession(structured_engine) as session:
        session.add(
            StructuredSpeechMessage(
                message_id=1001,
                webhook_id=900,
                guild_id=10,
                thread_id=30,
                user_id=50,
            )
        )
        await session.commit()

    member_user_id = await service.resolve_reference_user_id(
        ResolveStructuredSpeechReferenceQo(
            message_id=1000,
            author_id=40,
            author_is_bot=False,
            webhook_id=None,
        )
    )
    webhook_user_id = await service.resolve_reference_user_id(
        ResolveStructuredSpeechReferenceQo(
            message_id=1001,
            author_id=900,
            author_is_bot=True,
            webhook_id=900,
        )
    )

    assert member_user_id == 40
    assert webhook_user_id == 50


@pytest.mark.asyncio
async def test_reference_user_resolution_rejects_bots_and_unknown_webhooks(
    structured_engine: AsyncEngine,
) -> None:
    """验证 Bot 原生消息和未知 Webhook 不会产生无效用户提及。"""
    service = StructuredSpeechService(_create_bot(structured_engine))

    with pytest.raises(StructuredSpeechUserError, match="不能选择 Bot 消息"):
        await service.resolve_reference_user_id(
            ResolveStructuredSpeechReferenceQo(
                message_id=1000,
                author_id=40,
                author_is_bot=True,
                webhook_id=None,
            )
        )
    with pytest.raises(StructuredSpeechUserError, match="无法识别这条 Webhook 消息"):
        await service.resolve_reference_user_id(
            ResolveStructuredSpeechReferenceQo(
                message_id=1001,
                author_id=900,
                author_is_bot=True,
                webhook_id=900,
            )
        )


@pytest.mark.asyncio
async def test_global_punishment_does_not_require_proposal_record() -> None:
    """验证无提案记录的模板帖子仍会执行全局提案违规处罚检查。"""
    activity_repository = SimpleNamespace(
        get_user_activity=AsyncMock(return_value=None),
    )
    global_punishment_repository = SimpleNamespace(
        is_proposal_violation_restricted=AsyncMock(return_value=True),
    )
    fake_uow = SimpleNamespace(
        user_activity=activity_repository,
        global_proposal_punishment=global_punishment_repository,
    )

    class UnitOfWorkContext:
        """为处罚检查提供不包含提案仓储的工作单元。"""

        async def __aenter__(self):
            """返回测试工作单元。"""
            return fake_uow

        async def __aexit__(self, exc_type, exc_value, traceback):
            """结束测试工作单元上下文。"""
            return False

    service = StructuredSpeechService(MagicMock())
    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.UnitOfWork",
        return_value=UnitOfWorkContext(),
    ):
        punished = await service.is_user_punished(thread_id=30, user_id=50)

    assert punished is True
    global_punishment_repository.is_proposal_violation_restricted.assert_awaited_once_with(50)


@pytest.mark.asyncio
async def test_publish_rechecks_punishment_after_modal_opened() -> None:
    """验证填写表单期间受到处罚后，最终提交仍会被拒绝。"""
    service = StructuredSpeechService(MagicMock())
    service.active_modes[30] = StructuredSpeechModeDto(
        thread_id=30,
        forum_id=20,
        interval_seconds=120,
        previous_slowmode_delay=0,
    )
    service.is_user_punished = AsyncMock(return_value=True)
    thread = MagicMock(id=30)
    member = MagicMock(id=50)

    with pytest.raises(StructuredSpeechUserError, match="受到提案发言处罚"):
        await service.publish(
            thread=thread,
            member=member,
            qo=PublishStructuredSpeechQo(
                guild_id=10,
                thread_id=30,
                user_id=50,
                content="## 正文\n正文\n\n## 理由\n理由",
                cooldown_exempt=False,
            ),
            attachments=[],
        )


@pytest.mark.parametrize("attachment_count", [0, 1, 5])
@pytest.mark.asyncio
async def test_publish_forwards_allowed_attachment_counts_and_records_activity(
    structured_engine: AsyncEngine,
    attachment_count: int,
) -> None:
    """验证零个、一个和五个附件均可发送，并只在成功后记录活动。"""
    bot = _create_bot(structured_engine)
    service = StructuredSpeechService(bot)
    service.active_modes[30] = StructuredSpeechModeDto(
        thread_id=30,
        forum_id=20,
        interval_seconds=120,
        previous_slowmode_delay=15,
    )
    parent = MagicMock(id=20)
    thread = MagicMock(id=30)
    thread.parent = parent
    member = MagicMock(id=50, display_name="发言者")
    member.display_avatar.url = "https://example.invalid/avatar.png"
    webhook = MagicMock(id=900)
    sent = MagicMock(
        id=1001,
        created_at=datetime.now(timezone.utc),
        jump_url="https://example.invalid/message",
    )
    webhook.send = AsyncMock(return_value=sent)
    service.ensure_webhook = AsyncMock(return_value=webhook)
    service.is_user_punished = AsyncMock(return_value=False)

    files = [MagicMock() for _ in range(attachment_count)]
    attachments = []
    for file in files:
        attachment = MagicMock()
        attachment.to_file = AsyncMock(return_value=file)
        attachments.append(attachment)

    with (
        patch(
            "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.ForumChannel",
            type(parent),
        ),
        patch(
            "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.File",
            MagicMock,
        ),
        patch(
            "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.WebhookMessage",
            type(sent),
        ),
    ):
        result = await service.publish(
            thread=thread,
            member=member,
            qo=PublishStructuredSpeechQo(
                guild_id=10,
                thread_id=30,
                user_id=50,
                content="## 正文\n正文\n\n## 理由\n理由",
                cooldown_exempt=True,
            ),
            attachments=attachments,
        )

    assert result is sent
    send_kwargs = webhook.send.await_args.kwargs
    assert send_kwargs["allowed_mentions"].users is True
    assert send_kwargs["allowed_mentions"].roles is False
    assert send_kwargs["allowed_mentions"].everyone is False
    assert send_kwargs["allowed_mentions"].replied_user is True
    if attachment_count:
        assert send_kwargs["files"] == files
    else:
        assert "files" not in send_kwargs
    assert all(file.close.call_count == 1 for file in files)

    async with AsyncSession(structured_engine) as session:
        activity = (
            await session.exec(
                select(UserActivity).where(
                    UserActivity.user_id == 50,
                    UserActivity.context_thread_id == 30,
                )
            )
        ).one()
        message = (await session.exec(select(StructuredSpeechMessage))).one()

    assert activity.message_count == 1
    assert message.message_id == 1001
    assert message.webhook_id == 900


@pytest.mark.asyncio
async def test_attachment_read_failure_sends_nothing_and_consumes_no_cooldown(
    structured_engine: AsyncEngine,
) -> None:
    """验证任一附件读取失败时整条发送失败，且不写消息或活动记录。"""
    bot = _create_bot(structured_engine)
    service = StructuredSpeechService(bot)
    service.active_modes[30] = StructuredSpeechModeDto(
        thread_id=30,
        forum_id=20,
        interval_seconds=120,
        previous_slowmode_delay=15,
    )
    parent = MagicMock(id=20)
    thread = MagicMock(id=30)
    thread.parent = parent
    member = MagicMock(id=50)
    webhook = MagicMock(id=900)
    webhook.send = AsyncMock()
    service.ensure_webhook = AsyncMock(return_value=webhook)
    service.is_user_punished = AsyncMock(return_value=False)

    downloaded_file = MagicMock()
    successful_attachment = MagicMock()
    successful_attachment.to_file = AsyncMock(return_value=downloaded_file)
    failed_attachment = MagicMock()
    failed_attachment.to_file = AsyncMock(side_effect=RuntimeError("附件读取失败"))

    with (
        patch(
            "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.ForumChannel",
            type(parent),
        ),
        patch(
            "StellariaPact.cogs.StructuredSpeech.StructuredSpeechService.discord.File",
            MagicMock,
        ),
        pytest.raises(RuntimeError, match="附件读取失败"),
    ):
        await service.publish(
            thread=thread,
            member=member,
            qo=PublishStructuredSpeechQo(
                guild_id=10,
                thread_id=30,
                user_id=50,
                content="## 正文\n正文\n\n## 理由\n理由",
                cooldown_exempt=True,
            ),
            attachments=[successful_attachment, failed_attachment],
        )

    webhook.send.assert_not_awaited()
    downloaded_file.close.assert_called_once_with()
    assert await service.get_cooldown_remaining(thread_id=30, user_id=50) == 0
    async with AsyncSession(structured_engine) as session:
        assert list((await session.exec(select(UserActivity))).all()) == []
        assert list((await session.exec(select(StructuredSpeechMessage))).all()) == []


@pytest.mark.asyncio
async def test_bulk_message_deletion_rolls_back_activity_once(
    structured_engine: AsyncEngine,
) -> None:
    """验证批量和重复删除只按消息元数据幂等扣减一次活动。"""
    bot = _create_bot(structured_engine)
    service = StructuredSpeechService(bot)

    async with AsyncSession(structured_engine) as session:
        session.add(
            UserActivity(
                user_id=50,
                context_thread_id=30,
                message_count=2,
            )
        )
        session.add_all(
            [
                StructuredSpeechMessage(
                    message_id=1001,
                    webhook_id=900,
                    guild_id=10,
                    thread_id=30,
                    user_id=50,
                ),
                StructuredSpeechMessage(
                    message_id=1002,
                    webhook_id=900,
                    guild_id=10,
                    thread_id=30,
                    user_id=50,
                ),
            ]
        )
        await session.commit()

    qo = DeleteStructuredSpeechMessagesQo(message_ids={1001, 1002})
    await service.handle_message_deletions(qo)
    await service.handle_message_deletions(qo)

    async with AsyncSession(structured_engine) as session:
        activity = (
            await session.exec(
                select(UserActivity).where(
                    UserActivity.user_id == 50,
                    UserActivity.context_thread_id == 30,
                )
            )
        ).one()
        messages = list((await session.exec(select(StructuredSpeechMessage))).all())

    assert activity.message_count == 0
    assert all(message.deleted_at is not None for message in messages)
