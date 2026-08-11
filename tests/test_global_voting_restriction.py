import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.Cog import PunishmentCog
from StellariaPact.cogs.Punishment.logic.PunishmentLogic import PunishmentLogic
from StellariaPact.cogs.Punishment.views.PunishmentEmbedBuilder import PunishmentEmbedBuilder
from StellariaPact.cogs.Voting.qo import DeleteVoteQo
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.models.ConfirmationSession import ConfirmationSession
from StellariaPact.models.OperationLog import OperationLog
from StellariaPact.qo.user_vote import RecordVoteQo
from StellariaPact.repository.GlobalProposalPunishmentAlreadyActiveError import (
    GlobalProposalPunishmentAlreadyActiveError,
)
from StellariaPact.repository.GlobalProposalPunishmentNotFoundError import (
    GlobalProposalPunishmentNotFoundError,
)
from StellariaPact.repository.GlobalProposalPunishmentRepository import (
    GlobalProposalPunishmentRepository,
)
from StellariaPact.share.enums import LogOperationType, PunishmentType


class _FakeUnitOfWork:
    def __init__(self, **services):
        self.__dict__.update(services)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class GlobalProposalPunishmentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_restriction_lifecycle_preserves_history(self) -> None:
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            first = await repository.create_punishment(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                punishment_type=PunishmentType.PERMANENT_VOTING,
                reason="首次处罚",
                evidence_url="https://example.com/evidence.png",
                evidence_filename="evidence.png",
            )
            await session.commit()

            self.assertTrue(await repository.is_restricted(10))
            self.assertEqual(
                (await repository.get_active(10, PunishmentType.PERMANENT_VOTING)).id,
                first.id,
            )  # type: ignore

            with self.assertRaises(GlobalProposalPunishmentAlreadyActiveError):
                await repository.create_punishment(
                    target_user_id=10,
                    moderator_id=21,
                    origin_guild_id=31,
                    origin_channel_id=41,
                    punishment_type=PunishmentType.PERMANENT_VOTING,
                    reason="重复处罚",
                )

            lifted = await repository.lift_punishment(
                target_user_id=10,
                punishment_type=PunishmentType.PERMANENT_VOTING,
                lifted_by_id=22,
                lift_reason="复核后解除",
            )
            self.assertIsNotNone(lifted.lifted_at)
            await session.commit()
            self.assertFalse(await repository.is_restricted(10))

            second = await repository.create_punishment(
                target_user_id=10,
                moderator_id=23,
                origin_guild_id=99,
                origin_channel_id=98,
                punishment_type=PunishmentType.PERMANENT_VOTING,
                reason="再次处罚",
            )
            await session.commit()

            history = await repository.get_history(10)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0].id, second.id)
            self.assertEqual(history[1].id, first.id)

    async def test_lifting_missing_restriction_fails(self) -> None:
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            with self.assertRaises(GlobalProposalPunishmentNotFoundError):
                await repository.lift_punishment(
                    target_user_id=10,
                    punishment_type=PunishmentType.PERMANENT_VOTING,
                    lifted_by_id=20,
                    lift_reason="无有效处罚",
                )

    async def test_permanent_categories_coexist_and_have_distinct_scopes(self) -> None:
        """两种永久处罚可并存，新分类不进入普通投票和草案支持的默认限制。"""
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            for punishment_type in (
                PunishmentType.PERMANENT_VOTING,
                PunishmentType.PERMANENT_OBJECTION_CREATION,
            ):
                await repository.create_punishment(
                    target_user_id=10,
                    moderator_id=20,
                    origin_guild_id=30,
                    origin_channel_id=40,
                    punishment_type=punishment_type,
                    reason="测试处罚",
                )
            await session.commit()

            self.assertTrue(await repository.is_restricted(10))
            self.assertTrue(await repository.is_objection_creation_restricted(10))
            self.assertTrue(await repository.is_objection_support_restricted(10))

            await repository.lift_punishment(
                target_user_id=10,
                punishment_type=PunishmentType.PERMANENT_VOTING,
                lifted_by_id=20,
                lift_reason="仅解除投票限制",
            )
            await session.commit()

            self.assertFalse(await repository.is_restricted(10))
            self.assertTrue(await repository.is_objection_creation_restricted(10))
            self.assertTrue(await repository.is_objection_support_restricted(10))

    async def test_temporary_punishment_expires_and_can_be_archived(self) -> None:
        """限时处罚到期后应归档旧记录，并允许创建新的同类型处罚。"""
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            expired = await repository.create_punishment(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="已过期处罚",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            await session.commit()
            self.assertFalse(await repository.is_proposal_violation_restricted(10))

            replacement = await repository.create_punishment(
                target_user_id=10,
                moderator_id=21,
                origin_guild_id=30,
                origin_channel_id=40,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="新处罚",
                expires_at=datetime.now(timezone.utc) + timedelta(days=3),
            )
            await session.commit()

            self.assertTrue(await repository.is_proposal_violation_restricted(10))
            self.assertEqual(
                (await repository.get_active(10, PunishmentType.PROPOSAL_VIOLATION)).id,
                replacement.id,
            )  # type: ignore[union-attr]
            history = await repository.get_history(10)
            archived = next(record for record in history if record.id == expired.id)
            self.assertEqual(archived.lift_reason, "处罚自然到期后归档")
            self.assertEqual(archived.lifted_at, archived.expires_at)

    async def test_active_temporary_punishment_rejects_duplicate(self) -> None:
        """仍在生效的限时处罚必须拒绝重复创建，且不得生成覆盖历史。"""
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            await repository.create_punishment(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="生效中处罚",
                expires_at=datetime.now(timezone.utc) + timedelta(days=2),
            )
            await session.commit()

            with self.assertRaises(GlobalProposalPunishmentAlreadyActiveError):
                await repository.create_punishment(
                    target_user_id=10,
                    moderator_id=21,
                    origin_guild_id=30,
                    origin_channel_id=40,
                    punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                    reason="重复处罚",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=3),
                )

            self.assertEqual(len(await repository.get_history(10)), 1)

    async def test_announcement_message_locations_can_be_saved(self) -> None:
        """仓储应按处罚主键保存原始处罚公示和跨频道解除公示位置。"""
        async with AsyncSession(self.engine) as session:
            repository = GlobalProposalPunishmentRepository(session)
            punishment = await repository.create_punishment(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                punishment_type=PunishmentType.PERMANENT_VOTING,
                reason="测试处罚",
            )
            self.assertIsNotNone(punishment.id)
            await repository.set_punishment_message_id(punishment.id, 50)  # type: ignore[arg-type]
            await repository.set_resolution_message(
                punishment.id,  # type: ignore[arg-type]
                guild_id=31,
                channel_id=41,
                message_id=51,
            )
            await session.commit()

            record = (await repository.get_history(10))[0]

        self.assertEqual(record.punishment_message_id, 50)
        self.assertEqual(record.resolution_guild_id, 31)
        self.assertEqual(record.resolution_channel_id, 41)
        self.assertEqual(record.resolution_message_id, 51)

    async def test_successful_global_operations_are_audited(self) -> None:
        """永久、限时处罚及两类解除都应在同一业务事务中写入操作日志。"""
        db_handler = SimpleNamespace(get_session=lambda: AsyncSession(self.engine))
        logic = PunishmentLogic(SimpleNamespace(db_handler=db_handler))  # type: ignore[arg-type]
        common = {
            "target_user_id": 10,
            "moderator_id": 20,
            "origin_guild_id": 30,
            "origin_channel_id": 40,
            "reason": "审计测试",
            "evidence_url": "https://example.com/temporary.png",
            "evidence_filename": "temporary.png",
            "moderator_name": "moderator",
            "moderator_display_name": "管理者",
        }

        permanent_id = await logic.apply_global_voting_restriction(**common)
        objection_id = await logic.apply_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_OBJECTION_CREATION,
            **common,
        )
        violation_id, _ = await logic.apply_proposal_violation_punishment(
            **common,
            days=3,
        )
        with self.assertRaises(GlobalProposalPunishmentAlreadyActiveError):
            await logic.apply_proposal_violation_punishment(
                **common,
                days=5,
            )
        lifted_permanent_id, _ = await logic.lift_global_voting_restriction(
            target_user_id=10,
            lifted_by_id=20,
            lift_reason="解除永久处罚",
            moderator_name="moderator",
            moderator_display_name="管理者",
            guild_id=31,
            channel_id=41,
        )
        lifted_objection_id, _ = await logic.lift_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_OBJECTION_CREATION,
            target_user_id=10,
            lifted_by_id=20,
            lift_reason="解除永久异议权限处罚",
            moderator_name="moderator",
            moderator_display_name="管理者",
            guild_id=31,
            channel_id=41,
        )
        lifted_violation_id, _, _ = await logic.lift_proposal_violation_punishment(
            target_user_id=10,
            lifted_by_id=20,
            lift_reason="解除限时处罚",
            moderator_name="moderator",
            moderator_display_name="管理者",
            guild_id=31,
            channel_id=41,
        )

        async with AsyncSession(self.engine) as session:
            logs = list((await session.exec(select(OperationLog))).all())

        self.assertEqual(len(logs), 6)
        self.assertEqual(
            {log.action for log in logs},
            {
                "apply_permanent_voting",
                "apply_permanent_objection_creation",
                "apply_proposal_violation",
                "lift_permanent_voting",
                "lift_permanent_objection_creation",
                "lift_proposal_violation",
            },
        )
        self.assertTrue(all(log.op_type == LogOperationType.PUNISHMENT for log in logs))
        self.assertEqual(
            {log.target_id for log in logs},
            {permanent_id, objection_id, violation_id},
        )
        self.assertEqual(lifted_permanent_id, permanent_id)
        self.assertEqual(lifted_objection_id, objection_id)
        self.assertEqual(lifted_violation_id, violation_id)
        self.assertTrue(all("temporary.png" not in (log.detail or "") for log in logs))


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
                    global_proposal_punishment=restriction_repository,
                    user_vote=user_vote_repository,
                )

                with patch(
                    "StellariaPact.cogs.Voting.VotingLogic.UnitOfWork",
                    return_value=uow,
                ):
                    with self.assertRaisesRegex(PermissionError, "全局提案处罚"):
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
        restriction_repository = SimpleNamespace(
            is_objection_support_restricted=AsyncMock(return_value=True)
        )
        uow = _FakeUnitOfWork(
            confirmation_session=confirmation_repository,
            global_proposal_punishment=restriction_repository,
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
            with self.assertRaisesRegex(PermissionError, "全局提案处罚"):
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
        restriction_repository = SimpleNamespace(
            is_objection_support_restricted=AsyncMock(return_value=True)
        )
        uow = _FakeUnitOfWork(
            confirmation_session=confirmation_repository,
            global_proposal_punishment=restriction_repository,
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
        restriction_repository.is_objection_support_restricted.assert_not_awaited()


class GlobalVotingRestrictionCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_commands_and_optional_evidence_parameter_are_registered(self) -> None:
        commands = {command.name: command for command in PunishmentCog.__cog_app_commands__}
        self.assertIn("永久剥夺权限", commands)
        self.assertIn("解除永久权限限制", commands)
        self.assertIn("提案违规处罚", commands)
        self.assertIn("解除提案违规处罚", commands)

        restrict_parameters = {
            parameter.display_name: parameter for parameter in commands["永久剥夺权限"].parameters
        }
        self.assertTrue(restrict_parameters["用户"].required)
        self.assertTrue(restrict_parameters["分类"].required)
        self.assertEqual(
            {choice.name for choice in restrict_parameters["分类"].choices},
            {"投票资格", "异议创建与附议"},
        )
        self.assertTrue(restrict_parameters["处罚理由"].required)
        self.assertFalse(restrict_parameters["处罚依据"].required)

        lift_parameters = {
            parameter.display_name: parameter
            for parameter in commands["解除永久权限限制"].parameters
        }
        self.assertTrue(lift_parameters["分类"].required)
        self.assertEqual(
            {choice.name for choice in lift_parameters["分类"].choices},
            {"投票资格", "异议创建与附议"},
        )

        violation_parameters = {
            parameter.display_name: parameter for parameter in commands["提案违规处罚"].parameters
        }
        self.assertTrue(violation_parameters["用户"].required)
        self.assertTrue(violation_parameters["天数"].required)
        self.assertEqual(violation_parameters["天数"].min_value, 1)
        self.assertEqual(violation_parameters["天数"].max_value, 30)
        self.assertTrue(violation_parameters["处罚理由"].required)
        self.assertFalse(violation_parameters["处罚依据"].required)

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

    def test_objection_restriction_embed_only_lists_creation_and_support(self) -> None:
        embed = PunishmentEmbedBuilder.create_permanent_restriction_embed(
            moderator=SimpleNamespace(mention="<@20>"),  # type: ignore[arg-type]
            target_user=SimpleNamespace(mention="<@10>"),  # type: ignore[arg-type]
            reason="测试处罚",
            origin_guild_name="测试服务器",
            punishment_type=PunishmentType.PERMANENT_OBJECTION_CREATION,
        )

        self.assertIn("发起异议、新增异议附议", embed.description or "")
        self.assertNotIn("异议投票", embed.description or "")
        self.assertNotIn("草案支持票", embed.description or "")

    def test_proposal_violation_embed_contains_expiry_and_scope(self) -> None:
        """限时处罚公示必须明确展示截止时间和完整限制范围。"""
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        embed = PunishmentEmbedBuilder.create_proposal_violation_embed(
            moderator=SimpleNamespace(mention="<@20>"),  # type: ignore[arg-type]
            target_user=SimpleNamespace(mention="<@10>"),  # type: ignore[arg-type]
            reason="测试处罚",
            origin_guild_name="测试服务器",
            days=7,
            expires_at=expires_at,
        )
        self.assertIn("草案支持票", embed.description or "")
        self.assertIn("创建提案", embed.description or "")
        self.assertIn(str(int(expires_at.timestamp())), embed.description or "")

    async def test_dm_failure_does_not_prevent_public_notice(self) -> None:
        """私信失败时仍应保留公开公示成功状态及其消息 ID。"""

        class Scheduler:
            async def submit(self, coroutine, priority):
                return await coroutine

        bot = SimpleNamespace(api_scheduler=Scheduler())
        cog = PunishmentCog(bot)  # type: ignore[arg-type]
        channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=99)))
        target = SimpleNamespace(
            id=10,
            send=AsyncMock(side_effect=RuntimeError("DM disabled")),
        )
        interaction = SimpleNamespace(channel=channel)

        public_sent, dm_sent, public_message_id = await cog._send_global_restriction_notifications(
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
        self.assertEqual(public_message_id, 99)
        channel.send.assert_awaited_once()

    async def test_dm_uses_exact_public_notice_link_without_mutating_public_embed(self) -> None:
        class Scheduler:
            async def submit(self, coroutine, priority):
                return await coroutine

        cog = PunishmentCog(SimpleNamespace(api_scheduler=Scheduler()))  # type: ignore[arg-type]
        channel = SimpleNamespace(id=40, send=AsyncMock(return_value=SimpleNamespace(id=99)))
        target = SimpleNamespace(id=10, send=AsyncMock())
        interaction = SimpleNamespace(channel=channel, channel_id=40, guild_id=30)
        embed = PunishmentEmbedBuilder.create_global_voting_restriction_embed(
            moderator=SimpleNamespace(mention="<@20>"),  # type: ignore[arg-type]
            target_user=SimpleNamespace(mention="<@10>"),  # type: ignore[arg-type]
            reason="测试处罚",
            origin_guild_name="测试服务器",
        )

        await cog._send_global_restriction_notifications(  # type: ignore[arg-type]
            interaction, target, embed
        )

        public_embed = channel.send.await_args.kwargs["embed"]
        dm_embed = target.send.await_args.kwargs["embed"]
        self.assertFalse(any(field.name == "操作来源" for field in public_embed.fields))
        source = next(field for field in dm_embed.fields if field.name == "操作来源")
        self.assertIn("https://discord.com/channels/30/40/99", source.value)

    async def test_dm_falls_back_to_source_channel_when_public_notice_fails(self) -> None:
        class Scheduler:
            async def submit(self, coroutine, priority):
                return await coroutine

        cog = PunishmentCog(SimpleNamespace(api_scheduler=Scheduler()))  # type: ignore[arg-type]
        channel = SimpleNamespace(id=40, send=AsyncMock(side_effect=RuntimeError("forbidden")))
        target = SimpleNamespace(id=10, send=AsyncMock())
        interaction = SimpleNamespace(channel=channel, channel_id=40, guild_id=30)
        embed = PunishmentEmbedBuilder.create_global_voting_restriction_embed(
            moderator=SimpleNamespace(mention="<@20>"),  # type: ignore[arg-type]
            target_user=SimpleNamespace(mention="<@10>"),  # type: ignore[arg-type]
            reason="测试处罚",
            origin_guild_name="测试服务器",
        )

        public_sent, dm_sent, _ = await cog._send_global_restriction_notifications(
            interaction,
            target,
            embed,  # type: ignore[arg-type]
        )

        self.assertFalse(public_sent)
        self.assertTrue(dm_sent)
        dm_embed = target.send.await_args.kwargs["embed"]
        source = next(field for field in dm_embed.fields if field.name == "操作来源")
        self.assertIn("https://discord.com/channels/30/40", source.value)
        self.assertNotIn("/99", source.value)

    async def test_message_location_writeback_failure_is_degraded(self) -> None:
        """消息位置回写失败只能记录错误，不得让已完成的 Discord 公示失败。"""
        cog = PunishmentCog(SimpleNamespace())  # type: ignore[arg-type]
        cog.logic = SimpleNamespace(
            set_punishment_message_id=AsyncMock(side_effect=RuntimeError("database unavailable")),
            set_resolution_message=AsyncMock(side_effect=RuntimeError("database unavailable")),
        )

        await cog._try_set_punishment_message_id(1, 50)
        await cog._try_set_resolution_message(
            1,
            guild_id=30,
            channel_id=40,
            message_id=51,
        )

        cog.logic.set_punishment_message_id.assert_awaited_once_with(1, 50)
        cog.logic.set_resolution_message.assert_awaited_once_with(
            1,
            guild_id=30,
            channel_id=40,
            message_id=51,
        )


if __name__ == "__main__":
    unittest.main()
