import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.listeners.InnerEventListener import InnerEventListener
from StellariaPact.cogs.Voting.listeners.ModerationEventListener import ModerationEventListener
from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.dto import ProposalDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.qo.user_vote import RecordVoteQo
from StellariaPact.share.enums import ProposalStatus


class VotePanelInitializationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(self.engine) as session:
            proposal = Proposal(
                discussion_thread_id=100,
                proposer_id=10,
                title="测试提案",
                content="提案正文",
                status=ProposalStatus.DISCUSSION,
            )
            session.add(proposal)
            await session.flush()
            self.proposal = ProposalDto.model_validate(proposal)
            await session.commit()

        async def submit(awaitable, priority):
            return await awaitable

        self.bot = SimpleNamespace(
            db_handler=SimpleNamespace(get_session=lambda: AsyncSession(self.engine)),
            config={"channels": {"voting_channel": 300}},
            api_scheduler=SimpleNamespace(submit=submit),
            dispatch=Mock(),
        )
        self.thread = SimpleNamespace(
            id=100,
            guild=SimpleNamespace(id=1),
            starter_message=SimpleNamespace(content="提案正文"),
            jump_url="https://discord.com/channels/1/100",
            send=AsyncMock(return_value=SimpleNamespace(id=200)),
        )
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=400))
        self.listener = ModerationEventListener(self.bot)
        self.listener._send_intake_founders_panel = AsyncMock()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def create_panel(self, options, intake_id=None):
        with patch(
            "StellariaPact.cogs.Voting.listeners.ModerationEventListener."
            "DiscordUtils.fetch_channel",
            new=AsyncMock(return_value=self.channel),
        ):
            await self.listener.on_vote_session_created(
                proposal_dto=self.proposal,
                options=options,
                duration_hours=72,
                anonymous=True,
                realtime=True,
                notify=True,
                create_in_voting_channel=True,
                notify_creation_role=False,
                thread=self.thread,
                intake_id=intake_id,
            )
        self.thread.send.assert_awaited_once()
        self.channel.send.assert_awaited_once()

    async def test_empty_panel_creates_session_and_mirror_without_default_option(self):
        await self.create_panel([], intake_id=7)
        async with AsyncSession(self.engine) as session:
            vote = (await session.exec(select(VoteSession))).one()
            self.assertEqual(vote.total_choices, 0)
            self.assertEqual(vote.status, 1)
            self.assertEqual(vote.context_message_id, 200)
            self.assertEqual(vote.voting_channel_message_id, 400)
            self.assertEqual(list((await session.exec(select(VoteOption))).all()), [])

        for sender in (self.thread.send, self.channel.send):
            kwargs = sender.await_args.kwargs
            self.assertEqual(kwargs["embeds"][1].description, "暂无选项")
            self.assertNotIn("支持提案", str([e.to_dict() for e in kwargs["embeds"]]))
        self.listener._send_intake_founders_panel.assert_awaited_once_with(
            7, self.proposal.title, self.thread.jump_url
        )

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=10), followup=SimpleNamespace(send=AsyncMock())
        )
        await InnerEventListener(self.bot)._internal_handle_manage_vote(interaction, 100, 200)
        interaction.followup.send.assert_awaited_once_with(
            "当前暂无可管理的投票选项。", ephemeral=True
        )

    async def test_founders_event_sends_list_without_creating_vote(self):
        await self.listener.on_intake_founders_panel_requested(
            intake_id=7,
            proposal_title=self.proposal.title,
            thread_url=self.thread.jump_url,
        )
        self.listener._send_intake_founders_panel.assert_awaited_once_with(
            7, self.proposal.title, self.thread.jump_url
        )
        self.thread.send.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        async with AsyncSession(self.engine) as session:
            self.assertEqual(list((await session.exec(select(VoteSession))).all()), [])
            self.assertEqual(list((await session.exec(select(VoteOption))).all()), [])

    async def test_explicit_options_are_preserved(self):
        await self.create_panel(["同意方案甲", "同意方案乙"])
        async with AsyncSession(self.engine) as session:
            vote = (await session.exec(select(VoteSession))).one()
            options = (
                await session.exec(select(VoteOption).order_by(VoteOption.choice_index))
            ).all()
            self.assertEqual(vote.total_choices, 2)
            self.assertEqual([opt.choice_text for opt in options], ["同意方案甲", "同意方案乙"])
            self.assertEqual([opt.choice_index for opt in options], [1, 2])
        self.listener._send_intake_founders_panel.assert_not_awaited()

    async def test_first_option_can_be_added_refreshed_and_voted_on(self):
        await self.create_panel([])
        inner = InnerEventListener(self.bot)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=10, display_name="提案人", mention="<@10>"),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch(
            "StellariaPact.cogs.Voting.listeners.InnerEventListener.DiscordUtils.fetch_thread",
            new=AsyncMock(return_value=self.thread),
        ):
            await inner.on_new_option_submitted(
                interaction=interaction,
                message_id=200,
                thread_id=100,
                option_type=0,
                option_text="  新方案  ",
            )
        interaction.followup.send.assert_not_awaited()
        event, details = self.bot.dispatch.call_args.args
        self.assertEqual(event, "vote_details_updated")
        self.assertEqual(details.total_choices, 1)
        self.assertEqual(details.normal_options[0].choice_index, 1)
        self.assertEqual(details.normal_options[0].choice_text, "新方案")

        with patch.object(
            inner.logic,
            "_get_combined_eligibility_data",
            new=AsyncMock(return_value=(True, None, None)),
        ):
            voted = await inner.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=20,
                    message_id=200,
                    thread_id=100,
                    choice=1,
                )
            )
        self.assertEqual(voted.normal_options[0].approve_votes, 1)
        async with AsyncSession(self.engine) as session:
            vote = (await session.exec(select(VoteSession))).one()
            self.assertEqual(vote.total_choices, 1)


class VoteViewCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_registration_routes_legacy_button_ids(self):
        bot = SimpleNamespace(dispatch=Mock())
        view = VoteView(bot)
        client = discord.Client(intents=discord.Intents.none())
        client.add_view(view)
        self.assertTrue(view.is_persistent())
        expected = {
            "btn_manage_vote": ("panel_manage_vote_clicked", {}),
            "btn_manage_rules": ("panel_manage_rules_clicked", {}),
            "btn_create_normal": ("panel_create_option_clicked", {"option_type": 0}),
            "btn_create_objection": ("panel_create_option_clicked", {"option_type": 1}),
        }
        interaction = SimpleNamespace(message=SimpleNamespace(id=987654))
        try:
            with patch("StellariaPact.cogs.Voting.views.VoteView.safeDefer", new=AsyncMock()):
                for custom_id, (event, kwargs) in expected.items():
                    with self.subTest(custom_id=custom_id):
                        with patch.object(view, "_dispatch_item", return_value=None) as dispatch:
                            client._connection._view_store.dispatch_view(2, custom_id, interaction)
                        dispatch.assert_called_once()
                        item, routed_interaction = dispatch.call_args.args
                        self.assertEqual(item.custom_id, custom_id)
                        await item.callback(routed_interaction)
                        bot.dispatch.assert_called_with(event, interaction, **kwargs)
        finally:
            await client.close()

    async def test_active_and_closed_views_keep_existing_enablement(self):
        bot = SimpleNamespace(dispatch=Mock())
        active = VoteView(bot, SimpleNamespace(status=1))
        closed = VoteView(bot, SimpleNamespace(status=0))
        self.assertEqual(
            [item.label for item in active.children],
            [
                "投票",
                "规则管理",
                "创建投票选项",
                "创建异议",
            ],
        )
        self.assertEqual([item.row for item in active.children], [0, 0, 1, 1])
        self.assertEqual(
            [item.style for item in active.children],
            [
                discord.ButtonStyle.primary,
                discord.ButtonStyle.secondary,
                discord.ButtonStyle.secondary,
                discord.ButtonStyle.secondary,
            ],
        )
        self.assertTrue(all(not item.disabled for item in active.children))
        self.assertEqual([item.disabled for item in closed.children], [True, False, True, True])
