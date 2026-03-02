import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.share import StellariaPactBot, UnitOfWork, safeDefer

from .PunishmentEmbedBuilder import PunishmentEmbedBuilder

logger = logging.getLogger(__name__)

class PunishmentModal(discord.ui.Modal):
    """
    用于配置或修改用户处罚的模态框。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        target_user: discord.User | discord.Member,
        target_message: Optional[discord.Message] = None,
        existing_activity: Optional[UserActivity] = None
    ):
        is_edit = existing_activity is not None
        super().__init__(title="修改处罚设置" if is_edit else "踢出/处罚提案成员", timeout=1700)

        self.bot = bot
        self.target_user = target_user
        self.target_message = target_message

        # 计算预填数据
        default_voting = "是"
        default_mute_minutes = "0"

        if existing_activity:
            default_voting = "是" if existing_activity.validation == 1 else "否"
            if existing_activity.mute_end_time:
                # 数据库中的时间可能是 naive UTC，加上时区以便计算
                mute_end = existing_activity.mute_end_time
                if mute_end.tzinfo is None:
                    mute_end = mute_end.replace(tzinfo=timezone.utc)

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

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        try:
            # 1. 解析数据
            allow_voting_str = self.allow_voting_input.value.strip()
            if allow_voting_str == "是":
                is_voting_allowed = True
            elif allow_voting_str == "否":
                is_voting_allowed = False
            else:
                return await interaction.followup.send("“是否保留投票权”字段必须输入“是”或“否”。", ephemeral=True)

            try:
                mute_minutes = int(self.mute_duration_input.value)
                if mute_minutes < 0:
                    raise ValueError()
            except ValueError:
                return await interaction.followup.send("禁言时长必须是一个有效的非负整数。", ephemeral=True)

            reason = self.reason_input.value
            thread = interaction.channel
            moderator = interaction.user

            if not isinstance(thread, discord.Thread) or not isinstance(moderator, discord.Member):
                return

            # 计算截止时间 (存入DB的应当是 UTC naive datetime)
            mute_end_time = None
            if mute_minutes > 0:
                mute_end_time = (datetime.now(timezone.utc) + timedelta(minutes=mute_minutes)).replace(tzinfo=None)

            # 2. 数据库操作 (覆盖更新)
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.user_activity.update_user_validation_status(
                    user_id=self.target_user.id,
                    thread_id=thread.id,
                    is_valid=is_voting_allowed,
                    mute_end_time=mute_end_time,
                )
                await uow.commit()

            # 3. 派发事件更新内存缓存
            # 注意：派发给缓存的最好带上 timezone，方便计算
            aware_mute_end = mute_end_time.replace(tzinfo=timezone.utc) if mute_end_time else None
            self.bot.dispatch("thread_mute_updated", thread.id, self.target_user.id, aware_mute_end)

            # 4. 发送公示
            embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=self.target_user,
                reason=reason,
                target_message=self.target_message,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=aware_mute_end,
            )
            await self.bot.api_scheduler.submit(thread.send(embed=embed), priority=5)
            await interaction.followup.send("处罚配置已成功更新并公示。", ephemeral=True)

        except Exception as e:
            logger.error(f"处理处罚模态框时发生错误: {e}", exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
