import unittest
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import discord
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.views.PunishmentHistoryModal import (
    PunishmentHistoryModal,
)
from StellariaPact.models.PunishmentRecord import PunishmentRecord

# 绕过标准包导入限制，从文件路径直接加载被测服务模块
service_path = (
    Path(__file__).parents[1]
    / "src"
    / "StellariaPact"
    / "services"
    / "PunishmentRecordService.py"
)
service_spec = spec_from_file_location("punishment_record_service_under_test", service_path)
assert service_spec is not None and service_spec.loader is not None
service_module = module_from_spec(service_spec)
service_spec.loader.exec_module(service_module)
PunishmentRecordService = service_module.PunishmentRecordService


class PunishmentRecordTests(unittest.IsolatedAsyncioTestCase):
    """PunishmentRecordService 与 PunishmentHistoryModal 的单元测试。"""

    async def asyncSetUp(self) -> None:
        """每个用例前创建内存数据库并建表，隔离测试数据。"""
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(PunishmentRecord.__table__.create)

    async def asyncTearDown(self) -> None:
        """每个用例后释放数据库引擎。"""
        await self.engine.dispose()

    async def test_summary_is_scoped_counted_and_limited(self) -> None:
        """验证 get_summary 按帖子隔离计数、正确统计总数并限制返回条数。"""
        now = datetime.now(timezone.utc)
        async with AsyncSession(self.engine) as session:
            service = PunishmentRecordService(session)
            # 在同一帖子内创建多条处罚记录，每条设置不同的创建时间
            for index in range(4):
                record = await service.create_record(
                    guild_id=1,
                    thread_id=10,
                    target_user_id=20,
                    moderator_id=30,
                    reason=f"原因 {index}",
                    source_message_url=f"https://discord.com/channels/1/10/{index}",
                    voting_allowed=index % 2 == 0,
                    mute_end_time=None,
                )
                record.created_at = now + timedelta(minutes=index)

            # 在另一个帖子中创建一条记录，验证隔离性
            await service.create_record(
                guild_id=1,
                thread_id=99,
                target_user_id=20,
                moderator_id=30,
                reason="其他帖子",
                source_message_url=None,
                voting_allowed=True,
                mute_end_time=None,
            )
            await session.commit()

            # 查询目标帖子的汇总数据
            total, records = await service.get_summary(thread_id=10, target_user_id=20)

        # 总数为目标帖子的记录数，不包含其他帖子的记录
        self.assertEqual(total, 4)
        # 按创建时间倒序返回，默认限制最近三条
        self.assertEqual([record.reason for record in records], ["原因 3", "原因 2", "原因 1"])

    async def test_modal_uses_read_only_text_displays(self) -> None:
        """验证模态框所有子组件均为只读 TextDisplay，并正确渲染处罚详情。"""
        # 构造虚拟用户对象与一条处罚记录
        target_user = SimpleNamespace(display_name="测试用户", name="test", mention="<@20>")
        record = PunishmentRecord(
            guild_id=1,
            thread_id=10,
            target_user_id=20,
            moderator_id=30,
            reason="测试原因",
            source_message_url="https://discord.com/channels/1/10/100",
            voting_allowed=False,
            created_at=datetime.now(timezone.utc),
        )

        modal = PunishmentHistoryModal(target_user, 1, [record])

        # 摘要行与详情行共两个子组件，且均为 TextDisplay
        self.assertEqual(len(modal.children), 2)
        self.assertTrue(all(isinstance(item, discord.ui.TextDisplay) for item in modal.children))
        # 详情行包含投票资格与消息链接的渲染结果
        self.assertIn("剥夺投票资格", modal.children[1].content)
        self.assertIn("查看违规消息", modal.children[1].content)

    async def test_empty_modal_has_summary_only(self) -> None:
        """验证无处罚记录时模态框仅展示摘要信息，不含详情条目。"""
        # 构造虚拟用户对象，传入零条记录
        target_user = SimpleNamespace(display_name="测试用户", name="test", mention="<@20>")

        modal = PunishmentHistoryModal(target_user, 0, [])

        # 仅有一个摘要子组件，且内容提示暂无记录
        self.assertEqual(len(modal.children), 1)
        self.assertIn("暂无处罚记录", modal.children[0].content)


if __name__ == "__main__":
    unittest.main()
