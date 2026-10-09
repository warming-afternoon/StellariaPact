import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Intake.services.IntakeTransitionService import IntakeTransitionService
from StellariaPact.cogs.ThreadManage.Cog import ThreadManageCog
from StellariaPact.cogs.ThreadManage.dto.UpdateProposalContentDto import UpdateProposalContentDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums import IntakeStatus, ProposalStatus
from StellariaPact.share.ProposalContentFormatter import ProposalContentFormatter

RULES_SUFFIX = (
    "\n\n[提案规则](https://discord.com/channels/1134557553011998840/1554736946780049450)"
)

CUSTOM_RULES_URL = "https://example.com/proposal-rules"
CUSTOM_RULES_SUFFIX = f"\n\n[提案规则]({CUSTOM_RULES_URL})"


class ProposalRulesLinkLengthTests(unittest.TestCase):
    def test_room_for_link(self):
        self.assertEqual(
            ProposalContentFormatter.append_proposal_rules_link("首楼正文"),
            "首楼正文" + RULES_SUFFIX,
        )

    def test_exactly_at_limit_including_markdown_and_newlines(self):
        content = "文" * (2000 - len(RULES_SUFFIX))
        result = ProposalContentFormatter.append_proposal_rules_link(content)
        self.assertEqual(result, content + RULES_SUFFIX)
        self.assertEqual(len(result), 2000)

    def test_one_character_over_budget_keeps_original_content(self):
        content = "文" * (2001 - len(RULES_SUFFIX))
        self.assertEqual(ProposalContentFormatter.append_proposal_rules_link(content), content)

    def test_unset_or_empty_rules_url_uses_default(self):
        for url in (None, ""):
            with self.subTest(url=url):
                self.assertEqual(
                    ProposalContentFormatter.append_proposal_rules_link("正文", rules_url=url),
                    "正文" + RULES_SUFFIX,
                )

    def test_custom_url_length_determines_remaining_budget(self):
        for url in (CUSTOM_RULES_URL, CUSTOM_RULES_URL + "/details/" + "a" * 100):
            with self.subTest(url=url):
                suffix = f"\n\n[提案规则]({url})"
                content = "文" * (2000 - len(suffix))
                result = ProposalContentFormatter.append_proposal_rules_link(
                    content, rules_url=url
                )
                self.assertEqual(result, content + suffix)
                self.assertEqual(len(result), 2000)
                self.assertEqual(
                    ProposalContentFormatter.append_proposal_rules_link(
                        content + "文", rules_url=url
                    ),
                    content + "文",
                )

    def test_full_or_already_overlong_content_is_not_truncated(self):
        for size in (2000, 2001):
            with self.subTest(size=size):
                content = "文" * size
                self.assertEqual(
                    ProposalContentFormatter.append_proposal_rules_link(content), content
                )


class ProposalRulesLinkFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        self.thread = Mock(spec=discord.Thread)
        self.thread.id = 100
        self.thread.name = "[讨论中] 测试提案"
        self.thread.edit = AsyncMock()
        self.starter = SimpleNamespace(edit=AsyncMock())
        self.thread.fetch_message = AsyncMock(return_value=self.starter)
        self.forum = Mock(spec=discord.ForumChannel)
        self.forum.create_thread = AsyncMock(return_value=SimpleNamespace(thread=self.thread))
        self.bot = SimpleNamespace(
            db_handler=SimpleNamespace(get_session=lambda: AsyncSession(self.engine)),
            config={"channels": {"discussion": 50}},
            dispatch=Mock(),
            get_channel=Mock(return_value=self.thread),
        )
        self.helper = SimpleNamespace(
            resolve_forum_tag=Mock(return_value=None),
            post_discussion_rules=AsyncMock(),
            send_transition_confirmation_message=AsyncMock(),
            update_review_thread_message=AsyncMock(),
            update_review_thread_tags=AsyncMock(),
        )
        self.service = IntakeTransitionService(self.bot, self.helper)
        self.service._create_intake_transition_session = AsyncMock(return_value=None)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def seed_intake(self, reason="原因"):
        async with AsyncSession(self.engine) as session:
            intake = ProposalIntake(
                guild_id=1,
                author_id=10,
                title="测试提案",
                reason=reason,
                motion="动议",
                implementation="方案",
                executor="执行人",
                status=IntakeStatus.APPROVED,
            )
            session.add(intake)
            await session.flush()
            intake_id = intake.id
            await session.commit()
        return intake_id

    async def assert_database_has_no_auto_link(self):
        async with AsyncSession(self.engine) as session:
            proposal = (await session.exec(select(Proposal))).one()
            intake = (await session.exec(select(ProposalIntake))).one_or_none()
            self.assertNotIn("[提案规则](", proposal.content)
            if intake:
                self.assertNotIn("[提案规则](", intake.reason)

    async def create_discussion(self, *, legacy=False, long=False):
        intake_id = await self.seed_intake("文" * 2100 if long else "原因")
        with patch(
            "StellariaPact.cogs.Intake.services.IntakeTransitionService."
            "DiscordUtils.fetch_channel",
            new=AsyncMock(return_value=self.forum),
        ):
            if legacy:
                await self.service.handle_intake_transition_confirmed(intake_id)
            else:
                await self.service.handle_support_reached(intake_id)
        self.forum.create_thread.assert_awaited_once()
        content = self.forum.create_thread.await_args.kwargs["content"]
        self.assertLessEqual(len(content), 2000)
        self.assertIn("讨论帖创建时间", content)
        self.helper.post_discussion_rules.assert_awaited_once_with(self.thread)
        await self.assert_database_has_no_auto_link()
        await self.assert_no_automatic_vote()
        return intake_id, content

    async def assert_no_automatic_vote(self):
        self.assertNotIn(
            "vote_session_created",
            [call.args[0] for call in self.bot.dispatch.call_args_list],
        )
        async with AsyncSession(self.engine) as session:
            self.assertEqual(list((await session.exec(select(VoteSession))).all()), [])
            self.assertEqual(list((await session.exec(select(VoteOption))).all()), [])

    async def test_current_creation_adds_link_and_unlock_does_not_create_vote(self):
        intake_id, content = await self.create_discussion()
        self.assertTrue(content.endswith(RULES_SUFFIX))
        self.assertIn("🔒", content)
        with patch(
            "StellariaPact.cogs.Intake.services.IntakeTransitionService.DiscordUtils.fetch_thread",
            new=AsyncMock(return_value=self.thread),
        ):
            await self.service.handle_intake_transition_confirmed(intake_id)
        self.assertEqual(self.thread.edit.await_args.kwargs, {"locked": False})
        self.assertEqual(self.forum.create_thread.await_count, 1)
        args = self.bot.dispatch.call_args
        self.assertEqual(args.args, ("intake_founders_panel_requested",))
        self.assertEqual(args.kwargs["intake_id"], intake_id)
        self.assertEqual(args.kwargs["proposal_title"], "测试提案")
        self.assertEqual(args.kwargs["thread_url"], "https://discord.com/channels/1/100")
        await self.assert_no_automatic_vote()
        self.helper.update_review_thread_message.assert_awaited()
        self.helper.update_review_thread_tags.assert_awaited()

    async def test_unlock_preserves_existing_vote_session_and_options(self):
        intake_id, _ = await self.create_discussion()
        async with AsyncSession(self.engine) as session:
            proposal = (await session.exec(select(Proposal))).one()
            vote = VoteSession(
                guild_id=1,
                context_thread_id=100,
                context_message_id=200,
                voting_channel_message_id=300,
                proposal_id=proposal.id,
                total_choices=1,
                status=1,
            )
            session.add(vote)
            await session.flush()
            session.add(
                VoteOption(
                    session_id=vote.id,
                    option_type=0,
                    choice_index=1,
                    choice_text="已有选项",
                )
            )
            await session.commit()
        with patch(
            "StellariaPact.cogs.Intake.services.IntakeTransitionService.DiscordUtils.fetch_thread",
            new=AsyncMock(return_value=self.thread),
        ):
            await self.service.handle_intake_transition_confirmed(intake_id)
        async with AsyncSession(self.engine) as session:
            vote = (await session.exec(select(VoteSession))).one()
            option = (await session.exec(select(VoteOption))).one()
            self.assertEqual(vote.context_message_id, 200)
            self.assertEqual(vote.voting_channel_message_id, 300)
            self.assertEqual(vote.total_choices, 1)
            self.assertEqual(vote.status, 1)
            self.assertEqual(option.choice_text, "已有选项")
        self.assertNotIn(
            "vote_session_created",
            [call.args[0] for call in self.bot.dispatch.call_args_list],
        )

    async def test_legacy_creation_adds_link_without_creating_vote(self):
        intake_id, content = await self.create_discussion(legacy=True)
        self.assertTrue(content.endswith(RULES_SUFFIX))
        args = self.bot.dispatch.call_args
        self.assertEqual(args.args, ("intake_founders_panel_requested",))
        self.assertEqual(args.kwargs["intake_id"], intake_id)
        self.assertEqual(args.kwargs["proposal_title"], "测试提案")
        self.assertEqual(args.kwargs["thread_url"], "https://discord.com/channels/1/100")
        await self.assert_no_automatic_vote()
        self.helper.update_review_thread_message.assert_awaited()
        self.helper.update_review_thread_tags.assert_awaited()

    async def test_current_creation_uses_configured_rules_url(self):
        self.bot.config["proposal_rules_url"] = CUSTOM_RULES_URL
        _, content = await self.create_discussion()
        self.assertTrue(content.endswith(CUSTOM_RULES_SUFFIX))
        self.assertNotIn(RULES_SUFFIX, content)

    async def test_legacy_creation_uses_configured_rules_url(self):
        self.bot.config["proposal_rules_url"] = CUSTOM_RULES_URL
        _, content = await self.create_discussion(legacy=True)
        self.assertTrue(content.endswith(CUSTOM_RULES_SUFFIX))
        self.assertNotIn(RULES_SUFFIX, content)

    async def test_current_creation_preserves_truncation_without_reserving_link_space(self):
        _, content = await self.create_discussion(long=True)
        self.assertEqual(len(content), 2000)
        self.assertIn("……", content)
        self.assertNotIn(RULES_SUFFIX, content)

    async def test_legacy_creation_preserves_truncation_without_reserving_link_space(self):
        _, content = await self.create_discussion(legacy=True, long=True)
        self.assertEqual(len(content), 2000)
        self.assertIn("……", content)
        self.assertNotIn(RULES_SUFFIX, content)

    async def test_repeated_edits_regenerate_link_and_do_not_store_it(self):
        await self.assert_repeated_edits_use_rules_link(RULES_SUFFIX)

    async def test_repeated_edits_use_configured_rules_url_without_storing_it(self):
        self.bot.config["proposal_rules_url"] = CUSTOM_RULES_URL
        await self.assert_repeated_edits_use_rules_link(CUSTOM_RULES_SUFFIX)

    async def assert_repeated_edits_use_rules_link(self, expected_suffix):
        async with AsyncSession(self.engine) as session:
            proposal = Proposal(
                discussion_thread_id=100,
                proposer_id=10,
                title="测试提案",
                content="旧正文",
                status=ProposalStatus.DISCUSSION,
            )
            session.add(proposal)
            await session.flush()
            proposal_id = proposal.id
            await session.commit()
        dto = UpdateProposalContentDto(
            proposal_id=proposal_id,
            proposer_id=10,
            title="测试提案",
            reason="原因",
            motion="动议",
            implementation="方案",
            executor="执行人",
            thread_id=100,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=10),
            response=SimpleNamespace(is_done=Mock(return_value=True)),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        cog = ThreadManageCog(self.bot)
        cog._send_change_embed = AsyncMock()
        with patch("StellariaPact.cogs.ThreadManage.Cog.safeDefer", new=AsyncMock()):
            for _ in range(2):
                await cog.on_proposal_content_update_requested(dto, interaction)
                content = self.starter.edit.await_args.kwargs["content"]
                self.assertEqual(content, dto.format_content() + expected_suffix)
                self.assertEqual(content.count(expected_suffix), 1)
                await self.assert_database_has_no_auto_link()

            # 加长后仍保留完整正文，仅省略无法容纳的规则提醒。
            base_length = len(dto.format_content())
            dto.reason += "文" * (2001 - len(expected_suffix) - base_length)
            await cog.on_proposal_content_update_requested(dto, interaction)
            content = self.starter.edit.await_args.kwargs["content"]
            self.assertEqual(content, dto.format_content())
            self.assertNotIn(expected_suffix, content)
            self.assertLessEqual(len(content), 2000)
            await self.assert_database_has_no_auto_link()
        self.assertEqual(self.starter.edit.await_count, 3)
        self.assertEqual(interaction.followup.send.await_count, 3)
        for call in interaction.followup.send.await_args_list:
            self.assertIn("成功更新", call.args[0])
