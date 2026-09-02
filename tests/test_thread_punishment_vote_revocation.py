import unittest

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.logic.PunishmentLogic import PunishmentLogic
from StellariaPact.models.PunishmentRecord import PunishmentRecord
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums import VoteOptionStatus


class _TestDatabaseHandler:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    def get_session(self) -> AsyncSession:
        return AsyncSession(self.engine)


class _TestBot:
    def __init__(self, engine: AsyncEngine):
        self.db_handler = _TestDatabaseHandler(engine)


class ThreadPunishmentVoteRevocationTests(unittest.IsolatedAsyncioTestCase):
    target_thread_id = 100
    other_thread_id = 200
    target_user_id = 50
    other_user_id = 51

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        self.logic = PunishmentLogic(_TestBot(self.engine))  # type: ignore[arg-type]
        await self._seed_votes()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_votes(self) -> None:
        async with AsyncSession(self.engine) as session:
            active_session = VoteSession(
                guild_id=1,
                context_thread_id=self.target_thread_id,
                context_message_id=1000,
                total_choices=2,
                status=1,
            )
            ended_session = VoteSession(
                guild_id=1,
                context_thread_id=self.target_thread_id,
                context_message_id=1001,
                total_choices=1,
                status=0,
            )
            other_thread_session = VoteSession(
                guild_id=1,
                context_thread_id=self.other_thread_id,
                context_message_id=2000,
                total_choices=1,
                status=1,
            )
            session.add_all([active_session, ended_session, other_thread_session])
            await session.flush()

            assert active_session.id is not None
            assert ended_session.id is not None
            assert other_thread_session.id is not None

            session.add_all(
                [
                    VoteOption(
                        session_id=active_session.id,
                        option_type=0,
                        choice_index=1,
                        choice_text="进行中的普通选项",
                    ),
                    VoteOption(
                        session_id=active_session.id,
                        option_type=1,
                        choice_index=1,
                        choice_text="已关闭的异议",
                        voting_status=VoteOptionStatus.CLOSED,
                    ),
                    VoteOption(
                        session_id=ended_session.id,
                        option_type=0,
                        choice_index=1,
                        choice_text="已结束会话的选项",
                    ),
                    VoteOption(
                        session_id=other_thread_session.id,
                        option_type=0,
                        choice_index=1,
                        choice_text="其他帖子选项",
                    ),
                    UserVote(
                        session_id=active_session.id,
                        user_id=self.target_user_id,
                        option_type=0,
                        choice_index=1,
                        choice=1,
                    ),
                    UserVote(
                        session_id=active_session.id,
                        user_id=self.target_user_id,
                        option_type=1,
                        choice_index=1,
                        choice=0,
                    ),
                    UserVote(
                        session_id=active_session.id,
                        user_id=self.other_user_id,
                        option_type=0,
                        choice_index=1,
                        choice=1,
                    ),
                    UserVote(
                        session_id=ended_session.id,
                        user_id=self.target_user_id,
                        option_type=0,
                        choice_index=1,
                        choice=1,
                    ),
                    UserVote(
                        session_id=other_thread_session.id,
                        user_id=self.target_user_id,
                        option_type=0,
                        choice_index=1,
                        choice=1,
                    ),
                ]
            )
            await session.commit()

    async def _apply_punishment(self, voting_allowed: bool):
        return await self.logic.apply_thread_punishment(
            guild_id=1,
            thread_id=self.target_thread_id,
            target_user_id=self.target_user_id,
            moderator_id=99,
            reason="测试处罚",
            source_message_url="https://discord.test/messages/1",
            voting_allowed=voting_allowed,
            mute_end_time=None,
        )

    async def test_revocation_removes_only_active_votes_in_target_thread(self) -> None:
        result = await self._apply_punishment(voting_allowed=False)
        vote_details = result.vote_details_to_update

        async with AsyncSession(self.engine) as session:
            remaining_votes = (await session.exec(select(UserVote))).all()
            remaining_keys = {
                (vote.session_id, vote.user_id, vote.option_type, vote.choice_index)
                for vote in remaining_votes
            }
            sessions = (await session.exec(select(VoteSession))).all()
            session_ids = {session.context_message_id: session.id for session in sessions}

            self.assertNotIn(
                (session_ids[1000], self.target_user_id, 0, 1),
                remaining_keys,
            )
            self.assertIn(
                (session_ids[1000], self.target_user_id, 1, 1),
                remaining_keys,
            )
            self.assertIn(
                (session_ids[1000], self.other_user_id, 0, 1),
                remaining_keys,
            )
            self.assertIn(
                (session_ids[1001], self.target_user_id, 0, 1),
                remaining_keys,
            )
            self.assertIn(
                (session_ids[2000], self.target_user_id, 0, 1),
                remaining_keys,
            )

            activity = (
                await session.exec(
                    select(UserActivity).where(
                        UserActivity.user_id == self.target_user_id,
                        UserActivity.context_thread_id == self.target_thread_id,
                    )
                )
            ).one()
            self.assertEqual(activity.validation, 0)

            records = (await session.exec(select(PunishmentRecord))).all()
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0].voting_allowed)

        self.assertEqual(
            {details.context_message_id for details in vote_details},
            {1000, 1001},
        )
        active_details = next(
            details for details in vote_details if details.context_message_id == 1000
        )
        normal_option = next(
            option for option in active_details.normal_options if option.choice_index == 1
        )
        closed_objection = next(
            option for option in active_details.objection_options if option.choice_index == 1
        )
        self.assertEqual(normal_option.total_votes, 1)
        self.assertEqual(closed_objection.total_votes, 1)

    async def test_retaining_voting_rights_does_not_remove_votes(self) -> None:
        result = await self._apply_punishment(voting_allowed=True)

        async with AsyncSession(self.engine) as session:
            votes = (await session.exec(select(UserVote))).all()
            activity = (
                await session.exec(
                    select(UserActivity).where(
                        UserActivity.user_id == self.target_user_id,
                        UserActivity.context_thread_id == self.target_thread_id,
                    )
                )
            ).one()

        self.assertEqual(len(votes), 5)
        self.assertEqual(activity.validation, 1)
        self.assertGreater(result.punishment_record_id, 0)
        self.assertEqual(result.vote_details_to_update, [])

    async def test_revocation_without_active_votes_still_records_punishment(self) -> None:
        async with AsyncSession(self.engine) as session:
            active_session_id = (
                await session.exec(
                    select(VoteSession.id).where(VoteSession.context_message_id == 1000)
                )
            ).one()
            active_vote = (
                await session.exec(
                    select(UserVote).where(
                        UserVote.session_id == active_session_id,
                        UserVote.user_id == self.target_user_id,
                        UserVote.option_type == 0,
                    )
                )
            ).one()
            await session.delete(active_vote)
            await session.commit()

        result = await self._apply_punishment(voting_allowed=False)

        async with AsyncSession(self.engine) as session:
            activity = (
                await session.exec(
                    select(UserActivity).where(
                        UserActivity.user_id == self.target_user_id,
                        UserActivity.context_thread_id == self.target_thread_id,
                    )
                )
            ).one()
            records = (await session.exec(select(PunishmentRecord))).all()

        self.assertGreater(result.punishment_record_id, 0)
        self.assertEqual(result.vote_details_to_update, [])
        self.assertEqual(activity.validation, 0)
        self.assertEqual(len(records), 1)
