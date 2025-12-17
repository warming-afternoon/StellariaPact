import logging
from datetime import datetime, timedelta, timezone

import discord

from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.share import StellariaPactBot, UnitOfWork, safeDefer

logger = logging.getLogger(__name__)


class KickProposalModal(discord.ui.Modal, title="踢出提案"):
    """
    一个用于配置如何将用户踢出提案的模态框。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        original_interaction: discord.Interaction,
        target_message: discord.Message,
    ):
        super().__init__(timeout=1700)
        self.bot = bot
        self.original_interaction = original_interaction
        self.target_message = target_message
        self.kicked_user = target_message.author

        # 是否允许投票
        self.allow_voting_input = discord.ui.TextInput(
            label="是否保留投票权 (是/否)",
            placeholder="默认为“否”(剥夺投票权)。",
            required=True,
            default="否",
        )
        self.add_item(self.allow_voting_input)

        # 2. 禁言时长 (Text Input)
        self.mute_duration_input = discord.ui.TextInput(
            label="禁言时长 (分钟)",
            placeholder="输入一个整数，例如 60 (代表禁言1小时)。0代表不禁言。",
            required=True,
            default="0",
        )
        self.add_item(self.mute_duration_input)

        # 3. 原因 (Text Input)
        self.reason_input = discord.ui.TextInput(
            label="原因",
            style=discord.TextStyle.long,
            placeholder="请输入您执行此操作的理由...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, modal_interaction: discord.Interaction):
        await safeDefer(modal_interaction, ephemeral=True)

        try:
            # --- 数据解析和验证 ---
            allow_voting_str = self.allow_voting_input.value.strip()
            if allow_voting_str == "是":
                is_voting_allowed = True
            elif allow_voting_str == "否":
                is_voting_allowed = False
            else:
                await modal_interaction.followup.send(
                    "“是否保留投票权”字段必须输入“是”或“否”。", ephemeral=True
                )
                return

            reason = self.reason_input.value
            try:
                mute_minutes = int(self.mute_duration_input.value)
                if mute_minutes < 0:
                    raise ValueError("禁言时长不能为负数。")
            except ValueError:
                await modal_interaction.followup.send(
                    "禁言时长必须是一个有效的非负整数。", ephemeral=True
                )
                return

            mute_end_time = None
            if mute_minutes > 0:
                mute_end_time = datetime.now(timezone.utc) + timedelta(minutes=mute_minutes)

            thread = self.original_interaction.channel
            moderator = self.original_interaction.user
            if not isinstance(thread, discord.Thread) or not isinstance(moderator, discord.Member):
                return

            # --- 数据库操作 ---
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.user_activity.update_user_validation_status(
                    user_id=self.kicked_user.id,
                    thread_id=thread.id,
                    is_valid=is_voting_allowed,
                    mute_end_time=mute_end_time,
                )
                await uow.commit()

            # --- 事件派发与UI反馈 ---
            self.bot.dispatch(
                "thread_mute_updated",
                thread.id,
                self.kicked_user.id,
                mute_end_time,
            )

            embed = ModerationEmbedBuilder.create_kick_embed(
                moderator=moderator,
                kicked_user=self.kicked_user,
                reason=reason,
                target_message=self.target_message,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=mute_end_time,
            )
            await self.bot.api_scheduler.submit(thread.send(embed=embed), priority=5)

            await modal_interaction.followup.send("操作已成功执行。", ephemeral=True)

        except Exception as e:
            logger.error(f"在处理踢出提案时发生错误: {e}", exc_info=True)
            await modal_interaction.followup.send(
                "处理请求时发生错误，请联系技术人员。", ephemeral=True
            )
