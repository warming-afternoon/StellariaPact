import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.Cog import PunishmentCog
from StellariaPact.cogs.Punishment.views.PunishmentEmbedBuilder import PunishmentEmbedBuilder
from StellariaPact.cogs.Voting.qo import DeleteVoteQo
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.models.ConfirmationSession import ConfirmationSession
from StellariaPact.qo.user_vote import RecordVoteQo
from StellariaPact.repository.GlobalVotingRestrictionRepository import (
    GlobalVotingRestrictionAlreadyActiveError,
    GlobalVotingRestrictionNotFoundError,
    GlobalVotingRestrictionRepository,
)


class _FakeUnitOfWork:
    def __init__(self, **services):
        self.__dict__.update(services)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class GlobalVotingRestrictionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_restriction_lifecycle_preserves_history(self) -> None:
        async with AsyncSession(self.engine) as session:
            repository = GlobalVotingRestrictionRepository(session)
            first = await repository.create_restriction(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                reason="首次处罚",
                evidence_url="https://example.com/evidence.png",
                evidence_filename="evidence.png",
            )
            await session.commit()

            self.assertTrue(await repository.is_restricted(10))
            self.assertEqual((await repository.get_active(10)).id, first.id)  # type: ignore

            with self.assertRaises(GlobalVotingRestrictionAlreadyActiveError):
                await repository.create_restriction(
                    target_user_id=10,
                    moderator_id=21,
                    origin_guild_id=31,
                    origin_channel_id=41,
                    reason="重复处罚",
                )

            lifted = await repository.lift_restriction(
                target_user_id=10,
                lifted_by_id=22,
                lift_reason="复核后解除",
            )
            self.assertIsNotNone(lifted.lifted_at)
            await session.commit()
            self.assertFalse(await repository.is_restricted(10))

            second = await repository.create_restriction(
                target_user_id=10,
                moderator_id=23,
                origin_guild_id=99,
                origin_channel_id=98,
                reason="再次处罚",
            )
            await session.commit()

            history = await repository.get_history(10)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0].id, second.id)
            self.assertEqual(history[1].id, first.id)

    async def test_lifting_missing_restriction_fails(self) -> None:
        async with AsyncSession(self.engine) as session:
            repository = GlobalVotingRestrictionRepository(session)
            with self.assertRaises(GlobalVotingRestrictionNotFoundError):
                await repository.lift_restriction(
                    target_user_id=10,
                    lifted_by_id=20,
                    lift_reason="无有效处罚",
                )


class GlobalVotingRestrictionVotingLogicTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logic = VotingLogic(SimpleNamespace(db_handler=object()))  # type: ignore[arg-type]

    async def test_active_restriction_blocks_normal_and_objection_votes(self) -> None:
        for option_type in (0, 1):
            with self.subTest(option_type=option_type):
                vote_session = SimpleNamespace()
                vote_session_repository = SimpleNamespace(
                    get_vote_session_with_details=AsyncMock(return_value=vote_session)
                )
                restriction_repository = SimpleNamespace(
                    is_restricted=AsyncMock(return_value=True)
                )
                user_vote_repository = SimpleNamespace(record_vote=AsyncMock())
                uow = _FakeUnitOfWork(
                    vote_session=vote_session_repository,
                    global_voting_restriction=restriction_repository,
                    user_vote=user_vote_repository,
                )

                with patch(
                    "StellariaPact.cogs.Voting.VotingLogic.UnitOfWork",
                    return_value=uow,
                ):
                    with self.assertRaisesRegex(PermissionError, "永久剥夺"):
                        await self.logic.record_vote_and_get_details(
                            RecordVoteQo(
                                user_id=10,
                                message_id=20,
                                thread_id=30,
                                choice=1,
                                option_type=option_type,
                                choice_index=1,
                            )
                        )

                user_vote_repository.record_vote.assert_not_awaited()

    async def test_restricted_user_can_withdraw_existing_vote(self) -> None:
        vote_session = SimpleNamespace(id=1, status=1)
        vote_session_repository = SimpleNamespace(
            get_vote_session_with_details=AsyncMock(return_value=vote_session)
        )
        user_vote_repository = SimpleNamespace(delete_vote=AsyncMock(return_value=vote_session))
        vote_option_repository = SimpleNamespace(
            get_active_option=AsyncMock(return_value=object()),
            get_vote_options=AsyncMock(return_value=[]),
        )
        uow = _FakeUnitOfWork(
            vote_session=vote_session_repository,
            user_vote=user_vote_repository,
            vote_option=vote_option_repository,
        )
        expected = object()

        with (
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.UnitOfWork",
                return_value=uow,
            ),
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.VoteSessionRepository.get_vote_details_dto",
                return_value=expected,
            ),
        ):
            result = await self.logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=10,
                    message_id=20,
                    option_type=0,
                    choice_index=1,
                )
            )

        self.assertIs(result, expected)
        user_vote_repository.delete_vote.assert_awaited_once()

    async def test_active_restriction_blocks_new_objection_support(self) -> None:
        session = ConfirmationSession(
            id=1,
            context="objection_support",
            target_id=20,
            message_id=30,
            confirmed_parties={"发起人": 1},
            required_roles=[],
            created_at=datetime.now(timezone.utc),
        )
        confirmation_repository = SimpleNamespace(
            get_confirmation_session_by_message_id=AsyncMock(return_value=session),
            add_objection_supporter=AsyncMock(),
        )
        restriction_repository = SimpleNamespace(is_restricted=AsyncMock(return_value=True))
        uow = _FakeUnitOfWork(
            confirmation_session=confirmation_repository,
            global_voting_restriction=restriction_repository,
        )
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=30),
            user=SimpleNamespace(id=10),
        )

        with (
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.UnitOfWork",
                return_value=uow,
            ),
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.RoleGuard.hasRoles",
                return_value=True,
            ),
        ):
            with self.assertRaisesRegex(PermissionError, "永久剥夺"):
                await self.logic.handle_objection_support_click(  # type: ignore[arg-type]
                    interaction, "support"
                )

        confirmation_repository.add_objection_supporter.assert_not_awaited()

    async def test_restricted_user_can_withdraw_existing_objection_support(self) -> None:
        session = ConfirmationSession(
            id=1,
            context="objection_support",
            target_id=20,
            message_id=30,
            confirmed_parties={"发起人": 1, "支持者 1": 10},
            required_roles=[],
            created_at=datetime.now(timezone.utc),
        )

        async def remove_supporter(current_session, user_id):
            self.assertEqual(user_id, 10)
            current_session.confirmed_parties = {"发起人": 1}
            return current_session

        confirmation_repository = SimpleNamespace(
            get_confirmation_session_by_message_id=AsyncMock(return_value=session),
            remove_objection_supporter=AsyncMock(side_effect=remove_supporter),
        )
        restriction_repository = SimpleNamespace(is_restricted=AsyncMock(return_value=True))
        uow = _FakeUnitOfWork(
            confirmation_session=confirmation_repository,
            global_voting_restriction=restriction_repository,
        )
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=30),
            user=SimpleNamespace(id=10),
        )

        with (
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.UnitOfWork",
                return_value=uow,
            ),
            patch(
                "StellariaPact.cogs.Voting.VotingLogic.RoleGuard.hasRoles",
                return_value=True,
            ),
        ):
            result, completed = await self.logic.handle_objection_support_click(  # type: ignore
                interaction, "withdraw"
            )

        self.assertFalse(completed)
        self.assertEqual(result.confirmed_parties, {"发起人": 1})
        restriction_repository.is_restricted.assert_not_awaited()


class GlobalVotingRestrictionCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_commands_and_optional_evidence_parameter_are_registered(self) -> None:
        commands = {command.name: command for command in PunishmentCog.__cog_app_commands__}
        self.assertIn("永久剥夺投票资格", commands)
        self.assertIn("解除永久投票资格", commands)

        restrict_parameters = {
            parameter.display_name: parameter
            for parameter in commands["永久剥夺投票资格"].parameters
        }
        self.assertTrue(restrict_parameters["用户"].required)
        self.assertTrue(restrict_parameters["处罚理由"].required)
        self.assertFalse(restrict_parameters["处罚依据"].required)

    def test_restriction_embed_contains_evidence_and_scope(self) -> None:
        moderator = SimpleNamespace(mention="<@20>")
        target = SimpleNamespace(mention="<@10>")
        embed = PunishmentEmbedBuilder.create_global_voting_restriction_embed(
            moderator=moderator,  # type: ignore[arg-type]
            target_user=target,  # type: ignore[arg-type]
            reason="测试处罚",
            origin_guild_name="测试服务器",
            evidence_url="https://example.com/evidence.png",
        )

        self.assertIn("普通投票、异议投票、异议附议", embed.description or "")
        self.assertEqual(embed.image.url, "https://example.com/evidence.png")
        self.assertEqual(embed.fields[0].value, "测试处罚")

    async def test_dm_failure_does_not_prevent_public_notice(self) -> None:
        class Scheduler:
            async def submit(self, coroutine, priority):
                return await coroutine

        bot = SimpleNamespace(api_scheduler=Scheduler())
        cog = PunishmentCog(bot)  # type: ignore[arg-type]
        channel = SimpleNamespace(send=AsyncMock(return_value=None))
        target = SimpleNamespace(
            id=10,
            send=AsyncMock(side_effect=RuntimeError("DM disabled")),
        )
        interaction = SimpleNamespace(channel=channel)

        public_sent, dm_sent = await cog._send_global_restriction_notifications(
            interaction,  # type: ignore[arg-type]
            target,  # type: ignore[arg-type]
            PunishmentEmbedBuilder.create_global_voting_restriction_embed(
                moderator=SimpleNamespace(mention="<@20>"),  # type: ignore[arg-type]
                target_user=SimpleNamespace(mention="<@10>"),  # type: ignore[arg-type]
                reason="测试处罚",
                origin_guild_name="测试服务器",
            ),
        )

        self.assertTrue(public_sent)
        self.assertFalse(dm_sent)
        channel.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
