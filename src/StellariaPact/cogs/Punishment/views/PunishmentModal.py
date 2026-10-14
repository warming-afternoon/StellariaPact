from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord

from StellariaPact.dto.UserActivityDto import UserActivityDto

from ..qo import SubmitThreadPunishmentQo

if TYPE_CHECKING:
    from ..PunishmentCog import PunishmentCog


MAX_PUNISHMENT_EVIDENCE_FILES = 5


class PunishmentModal(discord.ui.Modal):
    """展示人工处罚表单，并将输入提交给处罚控制器。"""

    def __init__(
        self,
        cog: "PunishmentCog",
        target_user: discord.User | discord.Member,
        target_message: Optional[discord.Message] = None,
        existing_activity: Optional[UserActivityDto] = None,
    ):
        """构建人工处罚输入框，并根据独立活动快照预填设置。"""
        is_edit = existing_activity is not None
        super().__init__(title="修改处罚设置" if is_edit else "踢出/处罚提案成员", timeout=1700)

        self.cog = cog
        self.target_user = target_user
        self.target_message = target_message

        # 计算预填数据
        default_voting = "是"
        default_mute_minutes = "0"

        if existing_activity:
            default_voting = "是" if existing_activity.validation == 1 else "否"
            if existing_activity.mute_end_time:
                mute_end = existing_activity.mute_end_time
                now = datetime.now(timezone.utc)
                if mute_end > now:
                    delta_minutes = int((mute_end - now).total_seconds() / 60)
                    default_mute_minutes = str(delta_minutes)

        self.allow_voting_input = discord.ui.TextInput(
            label="是否保留投票权 (是/否)",
            placeholder="默认为“否”(剥夺投票权)。",
            required=True,
            default=default_voting,
        )
        self.add_item(self.allow_voting_input)

        self.mute_duration_input = discord.ui.TextInput(
            label="禁言时长 (自当前起算分钟数)",
            placeholder="例如 60 (代表禁言1小时)。0代表解除禁言/不禁言。",
            required=True,
            default=default_mute_minutes,
        )
        self.add_item(self.mute_duration_input)

        self.reason_input = discord.ui.TextInput(
            label="操作原因",
            style=discord.TextStyle.long,
            placeholder="请输入您执行或修改此处罚的理由，这将用于频道公示...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_input)

        self.evidence_upload = discord.ui.FileUpload(
            required=False,
            min_values=0,
            max_values=MAX_PUNISHMENT_EVIDENCE_FILES,
        )
        self.add_item(
            discord.ui.Label(
                text="处罚材料（可选）",
                description="最多上传 5 个文件，仅发送到处罚公示区。",
                component=self.evidence_upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """将人工处罚表单原始输入提交给控制器。"""
        # 视图不持有业务层或数据库对象，只传递独立的表单参数。
        await self.cog.submit_manual_punishment(
            interaction,
            SubmitThreadPunishmentQo(
                target_user=self.target_user,
                target_message=self.target_message,
                voting_input=self.allow_voting_input.value,
                mute_minutes_input=self.mute_duration_input.value,
                reason=self.reason_input.value,
                evidence=tuple(self.evidence_upload.values),
            ),
        )
