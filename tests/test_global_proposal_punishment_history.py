import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.Cog import PunishmentCog
from StellariaPact.cogs.Punishment.views.GlobalProposalPunishmentHistoryModal import (
    GlobalProposalPunishmentHistoryModal,
)
from StellariaPact.models.GlobalProposalPunishment import GlobalProposalPunishment
from StellariaPact.repository.GlobalProposalPunishmentRepository import (
    GlobalProposalPunishmentRepository,
)
from StellariaPact.share.enums import PunishmentType


class GlobalProposalPunishmentSummaryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """验证全局处罚历史摘要查询的计数、隔离和排序规则。"""

    async def asyncSetUp(self) -> None:
        """为每个测试创建独立的内存数据库。"""
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    async def asyncTearDown(self) -> None:
        """测试完成后释放数据库连接。"""
        await self.engine.dispose()

    async def test_summary_counts_all_history_and_returns_latest_four(self) -> None:
        """摘要应统计目标用户全部历史，并按时间和编号倒序返回最近四条。"""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        async with AsyncSession(self.engine) as session:
            for index in range(6):
                session.add(
                    self._build_record(
                        target_user_id=10,
                        reason=f"目标记录 {index}",
                        created_at=base_time + timedelta(hours=index),
                    )
                )
            session.add(
                self._build_record(
                    target_user_id=99,
                    reason="其他用户记录",
                    created_at=base_time + timedelta(days=1),
                )
            )
            await session.commit()

            total, records = await GlobalProposalPunishmentRepository(session).get_summary(
                10,
                limit=4,
            )

        self.assertEqual(total, 6)
        self.assertEqual([record.reason for record in records], [
            "目标记录 5",
            "目标记录 4",
            "目标记录 3",
            "目标记录 2",
        ])

    @staticmethod
    def _build_record(
        *,
        target_user_id: int,
        reason: str,
        created_at: datetime,
    ) -> GlobalProposalPunishment:
        """构造已解除记录，避免测试数据受有效处罚唯一索引影响。"""
        return GlobalProposalPunishment(
            target_user_id=target_user_id,
            moderator_id=20,
            origin_guild_id=30,
            origin_channel_id=40,
            punishment_type=PunishmentType.PROPOSAL_VIOLATION.value,
            reason=reason,
            created_at=created_at,
            expires_at=created_at + timedelta(days=1),
            lifted_by_id=21,
            lift_reason="测试结束",
            lifted_at=created_at + timedelta(hours=1),
        )


class GlobalProposalPunishmentHistoryModalTests(unittest.IsolatedAsyncioTestCase):
    """验证全局处罚历史只读弹窗的状态、链接和安全转义。"""

    def setUp(self) -> None:
        """准备固定当前时间和可供弹窗展示的虚拟用户。"""
        self.now = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
        self.target = SimpleNamespace(
            name="target",
            display_name="目标用户",
            mention="<@10>",
        )

    async def test_empty_history_only_displays_summary(self) -> None:
        """没有处罚历史时应只显示明确的空记录摘要。"""
        modal = GlobalProposalPunishmentHistoryModal(
            self.target,  # type: ignore[arg-type]
            0,
            [],
            now=self.now,
        )

        self.assertEqual(len(modal.children), 1)
        self.assertIsInstance(modal.children[0], discord.ui.TextDisplay)
        self.assertIn("暂无全局提案处罚记录", modal.children[0].content)

    async def test_modal_displays_all_statuses_links_and_escaped_reasons(self) -> None:
        """四条详情应覆盖全部状态，并正确展示链接及转义用户输入。"""
        records = [
            self._build_record(
                punishment_type=PunishmentType.PERMANENT_VOTING,
                reason="永久 *理由*",
            ),
            self._build_record(
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="过期理由",
                expires_at=self.now - timedelta(seconds=1),
            ),
            self._build_record(
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="解除理由",
                expires_at=self.now + timedelta(days=1),
                lifted_at=self.now - timedelta(hours=1),
                lift_reason="复核后 _解除_",
                lifted_by_id=22,
            ),
            self._build_record(
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason="覆盖理由",
                expires_at=self.now + timedelta(days=2),
                lifted_at=self.now - timedelta(hours=2),
                lift_reason="被新的同类型处罚覆盖",
                lifted_by_id=23,
                evidence_url="https://example.com/evidence.png",
            ),
        ]

        modal = GlobalProposalPunishmentHistoryModal(
            self.target,  # type: ignore[arg-type]
            8,
            records,
            now=self.now,
        )
        contents = [child.content for child in modal.children]
        details = "\n".join(contents[1:])

        self.assertEqual(len(modal.children), 5)
        self.assertIn("累计处罚：**8 次**", contents[0])
        self.assertIn("永久投票资格限制 · 生效中", details)
        self.assertIn("限时提案违规处罚 · 已到期", details)
        self.assertIn("限时提案违规处罚 · 已解除", details)
        self.assertIn("限时提案违规处罚 · 已覆盖", details)
        self.assertIn(r"永久 \*理由\*", details)
        self.assertIn(r"复核后 \_解除\_", details)
        self.assertIn("https://discord.com/channels/30/40", details)
        self.assertIn("https://example.com/evidence.png", details)

    def _build_record(
        self,
        *,
        punishment_type: PunishmentType,
        reason: str,
        expires_at: datetime | None = None,
        lifted_at: datetime | None = None,
        lift_reason: str | None = None,
        lifted_by_id: int | None = None,
        evidence_url: str | None = None,
    ) -> GlobalProposalPunishment:
        """按指定状态字段构造一条可展示的全局处罚记录。"""
        return GlobalProposalPunishment(
            target_user_id=10,
            moderator_id=20,
            origin_guild_id=30,
            origin_channel_id=40,
            punishment_type=punishment_type.value,
            reason=reason,
            evidence_url=evidence_url,
            created_at=self.now - timedelta(days=3),
            expires_at=expires_at,
            lifted_at=lifted_at,
            lift_reason=lift_reason,
            lifted_by_id=lifted_by_id,
        )


class GlobalProposalPunishmentContextMenuTests(unittest.IsolatedAsyncioTestCase):
    """验证用户头像上下文菜单的定义、生命周期和权限参数。"""

    def setUp(self) -> None:
        """创建带命令树和立即执行调度器的机器人替身。"""

        class Scheduler:
            async def submit(self, coroutine, priority):
                """立即等待被调度的 Discord API 协程。"""
                return await coroutine

        self.bot = SimpleNamespace(
            tree=MagicMock(),
            api_scheduler=Scheduler(),
            db_handler=object(),
        )
        self.cog = PunishmentCog(self.bot)  # type: ignore[arg-type]

    async def test_user_menu_is_registered_and_removed_with_cog(self) -> None:
        """Cog 加载和卸载时应分别注册及注销用户类型菜单。"""
        menu = self.cog.query_global_proposal_punishment_ctx
        self.assertEqual(menu.name, "查看全局提案处罚")
        self.assertEqual(menu.type, discord.AppCommandType.user)

        self.cog.cog_load()
        self.bot.tree.add_command.assert_any_call(menu)

        await self.cog.cog_unload()
        self.bot.tree.remove_command.assert_any_call(menu.name, type=menu.type)

    async def test_menu_uses_three_management_roles_and_rejects_dm(self) -> None:
        """菜单应校验三类管理角色，并在私信环境返回仅服务器可用提示。"""
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = None
        interaction.response.send_message = AsyncMock()
        member = SimpleNamespace(id=10)

        with patch(
            "StellariaPact.cogs.Punishment.Cog.RoleGuard.hasRoles",
            return_value=True,
        ) as has_roles:
            await self.cog.query_global_proposal_punishment_user(
                interaction,
                member,  # type: ignore[arg-type]
            )

        has_roles.assert_called_once_with(
            interaction,
            "councilModerator",
            "executionAuditor",
            "stewards",
        )
        interaction.response.send_message.assert_awaited_once_with(
            "此指令只能在服务器内使用。",
            ephemeral=True,
        )


if __name__ == "__main__":
    unittest.main()
