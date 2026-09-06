import unittest
from types import SimpleNamespace

from discord import app_commands

from StellariaPact.cogs.Intake.Cog import IntakeCog
from StellariaPact.cogs.Moderation.Cog import Moderation
from StellariaPact.cogs.Punishment.Cog import PunishmentCog
from StellariaPact.cogs.ThreadManage.Cog import ThreadManageCog


class CommandGroupingTests(unittest.TestCase):
    def test_intake_commands_are_registered_under_draft_group(self) -> None:
        self.assertTrue(IntakeCog.__cog_is_app_commands_group__)
        self.assertEqual(IntakeCog.__cog_group_name__, "草案")
        self.assertEqual(
            {command.name for command in IntakeCog.__cog_app_commands__},
            {"提交", "设置提交入口", "拒绝", "修改审核意见", "刷新显示"},
        )

    def test_punishment_commands_are_registered_under_one_group(self) -> None:
        cog = PunishmentCog(SimpleNamespace())  # type: ignore[arg-type]
        group = cog.__cog_app_commands_group__

        self.assertEqual(group.name, "提案处罚")
        self.assertEqual(
            {command.name for command in group.commands},
            {
                "永久剥夺权限",
                "解除永久权限限制",
                "提案违规处罚",
                "解除提案违规处罚",
            },
        )
        self.assertTrue(all(command.parent is group for command in group.commands))

    def test_only_administrator_state_commands_are_grouped_under_proposal(self) -> None:
        cog = Moderation(SimpleNamespace())  # type: ignore[arg-type]
        root_commands = {command.name: command for command in cog.get_app_commands()}

        self.assertEqual(set(root_commands), {"提案", "自助废弃"})
        proposal_group = root_commands["提案"]
        self.assertIsInstance(proposal_group, app_commands.Group)
        self.assertEqual(
            {command.name for command in proposal_group.commands},
            # 【PR2修改】"移除异议"由消息右键菜单降级为 /提案 斜杠命令
            {"进入执行", "完成", "废弃", "重新讨论", "移除异议"},
        )
        self.assertEqual(root_commands["自助废弃"].qualified_name, "自助废弃")

    def test_special_proposal_commands_are_grouped_without_moving_edit(self) -> None:
        cog = ThreadManageCog(SimpleNamespace())  # type: ignore[arg-type]
        root_commands = {command.name: command for command in cog.get_app_commands()}

        self.assertEqual(set(root_commands), {"特殊提案", "修改提案内容"})
        special_group = root_commands["特殊提案"]
        self.assertIsInstance(special_group, app_commands.Group)
        self.assertEqual(
            {command.name for command in special_group.commands},
            {"设置", "取消"},
        )
        self.assertEqual(root_commands["修改提案内容"].qualified_name, "修改提案内容")


if __name__ == "__main__":
    unittest.main()
