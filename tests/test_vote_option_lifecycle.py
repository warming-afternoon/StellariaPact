import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import discord
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Voting.qo import DeleteVoteQo
from StellariaPact.cogs.Voting.views.PaginatedManageView import PaginatedManageView
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto.vote_session import OptionResult, VoteDetailDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.qo.user_vote import RecordVoteQo
from StellariaPact.repository.UserVoteRepository import UserVoteRepository
from StellariaPact.repository.VoteOptionRepository import VoteOptionRepository
from StellariaPact.share.enums import ProposalStatus, VoteOptionStatus


class _TestDatabaseHandler:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    def get_session(self) -> AsyncSession:
        return AsyncSession(self.engine)


class VoteOptionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_proposal_vote(self) -> tuple[int, int]:
        async with AsyncSession(self.engine) as session:
            proposal = Proposal(
                discussion_thread_id=100,
                title="测试提案",
                content="测试内容",
                proposer_id=10,
                status=ProposalStatus.UNDER_OBJECTION,
            )
            session.add(proposal)
            await session.flush()

            vote_session = VoteSession(
                guild_id=1,
                context_thread_id=100,
                context_message_id=200,
                proposal_id=proposal.id,
                total_choices=2,
                status=1,
            )
            session.add(vote_session)
            await session.flush()

            session.add_all(
                [
                    VoteOption(
                        session_id=vote_session.id,  # type: ignore[arg-type]
                        option_type=0,
                        choice_index=1,
                        choice_text="普通选项",
                    ),
                    VoteOption(
                        session_id=vote_session.id,  # type: ignore[arg-type]
                        option_type=1,
                        choice_index=1,
                        choice_text="第一条异议",
                    ),
                    UserVote(
                        session_id=vote_session.id,  # type: ignore[arg-type]
                        user_id=50,
                        option_type=0,
                        choice_index=1,
                        choice=1,
                    ),
                    UserVote(
                        session_id=vote_session.id,  # type: ignore[arg-type]
                        user_id=50,
                        option_type=1,
                        choice_index=1,
                        choice=0,
                    ),
                ]
            )
            proposal_id = proposal.id
            vote_session_id = vote_session.id
            await session.commit()
            assert proposal_id is not None
            assert vote_session_id is not None
            return proposal_id, vote_session_id

    async def test_rediscuss_closes_only_active_objections(self) -> None:
        proposal_id, vote_session_id = await self._seed_proposal_vote()
        bot = SimpleNamespace(
            db_handler=_TestDatabaseHandler(self.engine),
            config={},
            dispatch=Mock(),
        )

        result = await ModerationLogic(bot).proposal_status_change(  # type: ignore[arg-type]
            proposal_id, ProposalStatus.DISCUSSION
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.status, ProposalStatus.DISCUSSION)  # type: ignore[union-attr]

        async with AsyncSession(self.engine) as session:
            options = (
                await session.exec(
                    select(VoteOption)
                    .where(VoteOption.session_id == vote_session_id)
                    .order_by(VoteOption.option_type, VoteOption.choice_index)  # type: ignore
                )
            ).all()
            normal, objection = options
            self.assertEqual(normal.voting_status, VoteOptionStatus.ACTIVE)
            self.assertIsNone(normal.closed_at)
            self.assertEqual(objection.voting_status, VoteOptionStatus.CLOSED)
            self.assertIsNotNone(objection.closed_at)
            self.assertEqual(objection.data_status, 1)

            votes = (
                await session.exec(select(UserVote).where(UserVote.session_id == vote_session_id))
            ).all()
            self.assertEqual(len(votes), 2)

        bot.dispatch.assert_called_once()

        voting_logic = VotingLogic(bot)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PermissionError, "已结束"):
            await voting_logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=50,
                    message_id=200,
                    thread_id=100,
                    option_type=1,
                    choice_index=1,
                    choice=1,
                )
            )
        with self.assertRaisesRegex(PermissionError, "已结束"):
            await voting_logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=50,
                    message_id=200,
                    option_type=1,
                    choice_index=1,
                )
            )

        # 同一会话中的普通投票仍可正常撤回。
        await voting_logic.delete_vote_and_get_details(
            DeleteVoteQo(
                user_id=50,
                message_id=200,
                option_type=0,
                choice_index=1,
            )
        )
        async with AsyncSession(self.engine) as session:
            votes = (
                await session.exec(select(UserVote).where(UserVote.session_id == vote_session_id))
            ).all()
            self.assertEqual(len(votes), 1)
            self.assertEqual(votes[0].option_type, 1)

    async def test_new_objection_uses_new_index_and_closed_votes_are_immutable(self) -> None:
        proposal_id, vote_session_id = await self._seed_proposal_vote()
        bot = SimpleNamespace(
            db_handler=_TestDatabaseHandler(self.engine),
            config={},
            dispatch=Mock(),
        )
        await ModerationLogic(bot).proposal_status_change(  # type: ignore[arg-type]
            proposal_id, ProposalStatus.DISCUSSION
        )

        async with AsyncSession(self.engine) as session:
            option_repository = VoteOptionRepository(session)
            new_objection = await option_repository.add_option(
                vote_session_id,
                option_type=1,
                text="后续新异议",
                creator_id=20,
                creator_name="测试用户",
            )
            session.add(
                UserVote(
                    session_id=vote_session_id,
                    user_id=50,
                    option_type=1,
                    choice_index=new_objection.choice_index,
                    choice=1,
                )
            )
            new_choice_index = new_objection.choice_index
            new_voting_status = new_objection.voting_status
            await session.commit()

            self.assertEqual(new_choice_index, 2)
            self.assertEqual(new_voting_status, VoteOptionStatus.ACTIVE)

        async with AsyncSession(self.engine) as session:
            deleted_count = await UserVoteRepository(session).delete_all_user_votes_in_thread(
                user_id=50, session_ids=[vote_session_id]
            )
            await session.commit()
            self.assertEqual(deleted_count, 2)

        async with AsyncSession(self.engine) as session:
            remaining_votes = (
                await session.exec(
                    select(UserVote).where(
                        UserVote.session_id == vote_session_id,
                        UserVote.user_id == 50,
                    )
                )
            ).all()
            self.assertEqual(len(remaining_votes), 1)
            self.assertEqual(remaining_votes[0].option_type, 1)
            self.assertEqual(remaining_votes[0].choice_index, 1)

    async def test_repeated_rediscuss_closes_only_new_objections_across_sessions(self) -> None:
        proposal_id, first_session_id = await self._seed_proposal_vote()
        async with AsyncSession(self.engine) as session:
            second_session = VoteSession(
                guild_id=1,
                context_thread_id=100,
                context_message_id=201,
                proposal_id=proposal_id,
                total_choices=2,
                status=1,
            )
            session.add(second_session)
            await session.flush()
            assert second_session.id is not None
            second_session_id = second_session.id
            session.add_all(
                [
                    VoteOption(
                        session_id=second_session_id,
                        option_type=0,
                        choice_index=1,
                        choice_text="第二会话普通选项",
                    ),
                    VoteOption(
                        session_id=second_session_id,
                        option_type=1,
                        choice_index=1,
                        choice_text="第二会话异议",
                    ),
                ]
            )
            await session.commit()

        bot = SimpleNamespace(
            db_handler=_TestDatabaseHandler(self.engine),
            config={},
            dispatch=Mock(),
        )
        logic = ModerationLogic(bot)  # type: ignore[arg-type]
        await logic.proposal_status_change(proposal_id, ProposalStatus.DISCUSSION)

        async with AsyncSession(self.engine) as session:
            first_closed = (
                await session.exec(
                    select(VoteOption).where(
                        VoteOption.session_id == first_session_id,
                        VoteOption.option_type == 1,
                        VoteOption.choice_index == 1,
                    )
                )
            ).one()
            original_closed_at = first_closed.closed_at

            proposal = await session.get(Proposal, proposal_id)
            assert proposal is not None
            proposal.status = ProposalStatus.UNDER_OBJECTION
            session.add(proposal)
            new_objection = await VoteOptionRepository(session).add_option(
                first_session_id,
                option_type=1,
                text="第二轮异议",
            )
            new_choice_index = new_objection.choice_index
            await session.commit()

        await logic.proposal_status_change(proposal_id, ProposalStatus.DISCUSSION)

        async with AsyncSession(self.engine) as session:
            options = (
                await session.exec(
                    select(VoteOption)
                    .where(
                        VoteOption.session_id.in_([first_session_id, second_session_id])  # type: ignore
                    )
                    .order_by(
                        VoteOption.session_id,
                        VoteOption.option_type,
                        VoteOption.choice_index,
                    )
                )
            ).all()
            normal_options = [option for option in options if option.option_type == 0]
            objection_options = [option for option in options if option.option_type == 1]

            self.assertTrue(
                all(option.voting_status == VoteOptionStatus.ACTIVE for option in normal_options)
            )
            self.assertTrue(
                all(
                    option.voting_status == VoteOptionStatus.CLOSED for option in objection_options
                )
            )
            original_objection = next(
                option
                for option in objection_options
                if option.session_id == first_session_id and option.choice_index == 1
            )
            self.assertEqual(original_objection.closed_at, original_closed_at)
            self.assertEqual(new_choice_index, 2)

        # 第一次刷新两个会话，第二次只刷新有新异议的会话。
        self.assertEqual(bot.dispatch.call_count, 3)


class VoteOptionLifecycleViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.closed_at = datetime.now(timezone.utc)
        self.closed_objection = OptionResult(
            option_id=1,
            creator_id=10,
            choice_index=1,
            choice_text="历史异议",
            approve_votes=2,
            reject_votes=3,
            total_votes=5,
            is_active=False,
            closed_at=self.closed_at,
        )

    def test_closed_objection_displays_final_result_when_realtime_is_off(self) -> None:
        details = VoteDetailDto(
            guild_id=1,
            context_thread_id=2,
            objection_id=None,
            voting_channel_message_id=None,
            is_anonymous=True,
            realtime_flag=False,
            notify_flag=True,
            end_time=None,
            context_message_id=3,
            status=1,
            total_choices=1,
            objection_options=[self.closed_objection],
        )

        embeds = VoteEmbedBuilder.create_vote_panel_embed_v2("测试提案", details)
        objection_embed = embeds[-1]
        self.assertIn("已结束", objection_embed.fields[0].name)
        self.assertIn("赞成异议: 2", objection_embed.fields[0].value)
        self.assertIn("反对异议: 3", objection_embed.fields[0].value)

    async def test_closed_objection_management_buttons_are_disabled(self) -> None:
        interaction = SimpleNamespace(user=SimpleNamespace(id=10))
        view = PaginatedManageView(
            bot=SimpleNamespace(),  # type: ignore[arg-type]
            interaction=interaction,  # type: ignore[arg-type]
            thread_id=2,
            msg_id=3,
            options=[self.closed_objection],
            option_type=1,
            user_has_builder_role=True,
        )

        buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]
        self.assertEqual(len(buttons), 3)
        self.assertTrue(all(button.disabled for button in buttons))


if __name__ == "__main__":
    unittest.main()
