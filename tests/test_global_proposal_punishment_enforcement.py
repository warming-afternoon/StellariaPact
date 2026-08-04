import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from StellariaPact.cogs.Intake.services.IntakeDraftService import IntakeDraftService
from StellariaPact.cogs.Intake.services.IntakeVoteService import IntakeVoteService
from StellariaPact.cogs.Punishment.listeners.PunishmentListener import PunishmentListener
from StellariaPact.cogs.Punishment.logic.PunishmentLogic import PunishmentLogic
from StellariaPact.cogs.Voting.listeners.InnerEventListener import InnerEventListener
from StellariaPact.share.enums import IntakeStatus


class _FakeUnitOfWork:
    def __init__(self, **services):
        self.__dict__.update(services)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def one_or_none(self):
        return self.value


class ProposalPunishmentEnforcementTests(unittest.IsolatedAsyncioTestCase):
    """验证全局提案处罚在各个业务入口的最终强制拦截。"""

    async def test_logic_rejects_duration_outside_one_to_thirty_days(self) -> None:
        """业务逻辑层必须拒绝小于 1 天或超过 30 天的处罚时长。"""
        logic = PunishmentLogic(SimpleNamespace(db_handler=object()))  # type: ignore
        for days in (0, 31):
            with self.assertRaisesRegex(ValueError, "1 至 30"):
                await logic.apply_proposal_violation_punishment(
                    target_user_id=10,
                    moderator_id=20,
                    origin_guild_id=30,
                    origin_channel_id=40,
                    days=days,
                    reason="测试",
                    evidence_url=None,
                    evidence_filename=None,
                    moderator_name="moderator",
                    moderator_display_name="管理者",
                )

    async def test_apply_punishment_returns_local_expiry_after_commit(self) -> None:
        """创建处罚提交后应返回局部截止时间，不再读取已过期的 ORM 属性。"""

        class ExpiringPunishment:
            """模拟提交后禁止读取属性的 ORM 实体。"""

            expired = False

            @property
            def expires_at(self):
                """提交后读取属性时模拟 SQLAlchemy 的隐式刷新异常。"""
                if self.expired:
                    raise RuntimeError("提交后不应读取 ORM 属性")
                return None

        punishment = ExpiringPunishment()
        punishment.id = 77
        captured_expiry = None

        async def create_punishment(**kwargs):
            """保存业务层计算的截止时间并返回模拟 ORM 实体。"""
            nonlocal captured_expiry
            captured_expiry = kwargs["expires_at"]
            return punishment

        async def commit():
            """模拟提交导致 ORM 实体字段过期。"""
            punishment.expired = True

        uow = _FakeUnitOfWork(
            global_proposal_punishment=SimpleNamespace(
                create_punishment=AsyncMock(side_effect=create_punishment)
            ),
            operation_log=SimpleNamespace(log_operation=AsyncMock()),
            commit=AsyncMock(side_effect=commit),
        )
        logic = PunishmentLogic(SimpleNamespace(db_handler=object()))  # type: ignore

        with patch(
            "StellariaPact.cogs.Punishment.logic.PunishmentLogic.UnitOfWork",
            return_value=uow,
        ):
            result = await logic.apply_proposal_violation_punishment(
                target_user_id=10,
                moderator_id=20,
                origin_guild_id=30,
                origin_channel_id=40,
                days=3,
                reason="测试处罚",
                evidence_url=None,
                evidence_filename=None,
                moderator_name="moderator",
                moderator_display_name="管理者",
            )

        self.assertEqual(result, (77, captured_expiry))
        uow.commit.assert_awaited_once()
        uow.operation_log.log_operation.assert_awaited_once()

    async def test_cache_loader_converts_orm_records_inside_unit_of_work(self) -> None:
        """启动缓存加载应在会话关闭前把 ORM 记录转换成普通元组。"""
        expires_at = datetime.now(timezone.utc) + timedelta(days=2)

        class SessionBoundPunishment:
            """模拟会话关闭后无法读取字段的 ORM 实体。"""

            def __init__(self, owner):
                self.owner = owner

            @property
            def target_user_id(self):
                """仅允许在工作单元有效期间读取目标用户。"""
                if self.owner.closed:
                    raise RuntimeError("会话关闭后不应读取 ORM 属性")
                return 10

            @property
            def expires_at(self):
                """仅允许在工作单元有效期间读取截止时间。"""
                if self.owner.closed:
                    raise RuntimeError("会话关闭后不应读取 ORM 属性")
                return expires_at

        class ClosingUnitOfWork:
            """退出上下文时标记会话已经关闭。"""

            def __init__(self):
                self.closed = False
                self.global_proposal_punishment = SimpleNamespace(
                    get_active_by_type=AsyncMock(return_value=[SessionBoundPunishment(self)])
                )

            async def __aenter__(self):
                """进入工作单元并提供处罚仓储。"""
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                """模拟真实工作单元关闭数据库会话。"""
                self.closed = True
                return False

        uow = ClosingUnitOfWork()
        listener = object.__new__(PunishmentListener)
        listener.bot = SimpleNamespace(db_handler=object())
        listener.active_proposal_violations = {}

        with patch(
            "StellariaPact.cogs.Punishment.listeners.PunishmentListener.UnitOfWork",
            return_value=uow,
        ):
            await listener._load_active_proposal_violations_into_cache()

        self.assertTrue(uow.closed)
        self.assertEqual(listener.active_proposal_violations, {10: expires_at})

    async def test_final_draft_submission_is_blocked(self) -> None:
        """即使用户已打开表单，最终提交草案时仍必须再次检查处罚。"""
        punishment_repository = SimpleNamespace(
            is_proposal_violation_restricted=AsyncMock(return_value=True)
        )
        uow = _FakeUnitOfWork(global_proposal_punishment=punishment_repository)
        service = IntakeDraftService(SimpleNamespace(db_handler=object()))  # type: ignore
        dto = SimpleNamespace(author_id=10, guild_id=20)

        with patch(
            "StellariaPact.cogs.Intake.services.IntakeDraftService.UnitOfWork",
            return_value=uow,
        ):
            with self.assertRaisesRegex(PermissionError, "无法创建或提交"):
                await service.process_submit_intake(dto, SimpleNamespace())  # type: ignore

    async def test_new_intake_support_is_blocked_before_insert(self) -> None:
        """受罚用户不能新增草案支持票，且拦截必须发生在数据库写入前。"""
        intake = SimpleNamespace(id=1, status=IntakeStatus.SUPPORT_COLLECTING)
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _ScalarResult(SimpleNamespace(id=2)),
                    _ScalarResult(None),
                ]
            ),
            add=Mock(),
        )
        punishment_repository = SimpleNamespace(is_restricted=AsyncMock(return_value=True))
        uow = SimpleNamespace(
            intake=SimpleNamespace(get_intake_by_voting_message_id=AsyncMock(return_value=intake)),
            session=session,
            global_proposal_punishment=punishment_repository,
        )
        service = IntakeVoteService(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())  # type: ignore

        with self.assertRaisesRegex(PermissionError, "无法新增草案支持票"):
            await service.handle_support_toggle(uow, user_id=10, message_id=20)  # type: ignore
        session.add.assert_not_called()

    async def test_final_objection_creation_is_blocked(self) -> None:
        """处罚期间，即使通过旧异议表单提交，也不能创建异议附议面板。"""
        punishment_repository = SimpleNamespace(
            is_proposal_violation_restricted=AsyncMock(return_value=True)
        )
        uow = _FakeUnitOfWork(global_proposal_punishment=punishment_repository)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=10, display_name="user"),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        listener = InnerEventListener(SimpleNamespace(db_handler=object()))  # type: ignore

        with patch(
            "StellariaPact.cogs.Voting.listeners.InnerEventListener.UnitOfWork",
            return_value=uow,
        ):
            await listener.on_new_option_submitted(
                interaction=interaction,  # type: ignore[arg-type]
                message_id=20,
                thread_id=30,
                option_type=1,
                option_text="异议内容",
            )

        interaction.followup.send.assert_awaited_once()
        self.assertIn("无法创建异议", interaction.followup.send.await_args.args[0])

    async def test_global_punishment_deletes_messages_only_in_proposal_threads(self) -> None:
        """全局发言限制只删除正式提案讨论帖消息，不影响其他帖子。"""

        class FakeThread:
            def __init__(self, thread_id: int):
                self.id = thread_id

        listener = object.__new__(PunishmentListener)
        listener.bot = SimpleNamespace(db_handler=object())
        listener.active_mutes = {}
        listener.active_proposal_violations = {10: datetime.now(timezone.utc) + timedelta(days=1)}
        message = SimpleNamespace(
            author=SimpleNamespace(id=10, bot=False),
            channel=FakeThread(30),
            guild=SimpleNamespace(id=40),
            delete=AsyncMock(),
        )
        uow = _FakeUnitOfWork(
            proposal=SimpleNamespace(
                get_proposal_by_thread_id=AsyncMock(return_value=SimpleNamespace(id=1))
            )
        )

        with (
            patch(
                "StellariaPact.cogs.Punishment.listeners.PunishmentListener.discord.Thread",
                FakeThread,
            ),
            patch(
                "StellariaPact.cogs.Punishment.listeners.PunishmentListener.UnitOfWork",
                return_value=uow,
            ),
        ):
            await listener.on_message(message)  # type: ignore[arg-type]

        message.delete.assert_awaited_once()

        message.delete.reset_mock()
        uow.proposal.get_proposal_by_thread_id.return_value = None
        with (
            patch(
                "StellariaPact.cogs.Punishment.listeners.PunishmentListener.discord.Thread",
                FakeThread,
            ),
            patch(
                "StellariaPact.cogs.Punishment.listeners.PunishmentListener.UnitOfWork",
                return_value=uow,
            ),
        ):
            await listener.on_message(message)  # type: ignore[arg-type]

        message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
