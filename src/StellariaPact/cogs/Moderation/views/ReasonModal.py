import logging

import discord

from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger("stellaria_pact.moderation")


class ReasonModal(discord.ui.Modal, title="操作理由"):
    """
    一个用于获取操作理由的模态框。
    """

    reason_input = discord.ui.TextInput(
        label="理由",
        style=discord.TextStyle.long,
        placeholder="请输入您执行此操作的理由...",
        required=True,
        max_length=4000,
    )

    def __init__(
        self,
        bot: StellariaPactBot,
        original_interaction: discord.Interaction,
        target_message: discord.Message,
    ):
        super().__init__(timeout=1800)
        self.bot = bot
        self.original_interaction = original_interaction
        self.target_message = target_message
        self.kicked_user = target_message.author

    async def on_submit(self, modal_interaction: discord.Interaction):
        """
        当用户提交模态框时调用。
        这里处理的是一个全新的、独立的交互。
        """
        await self.bot.api_scheduler.submit(safeDefer(modal_interaction), priority=1)

        try:
            # 从原始交互中获取上下文信息
            thread = self.original_interaction.channel
            moderator = self.original_interaction.user

            # 类型守卫
            if not isinstance(thread, discord.Thread) or not isinstance(moderator, discord.Member):
                # 这种情况理论上不应发生，因为 Cog 层已经检查过
                await self.bot.api_scheduler.submit(
                    modal_interaction.followup.send("上下文信息无效，操作失败。", ephemeral=True),
                    priority=1,
                )
                return

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 前置检查：防止重复操作
                activity = await uow.moderation.get_user_activity(
                    user_id=self.kicked_user.id, thread_id=thread.id
                )
                if activity and not activity.validation:
                    await self.bot.api_scheduler.submit(
                        modal_interaction.followup.send(
                            "该用户已被踢出，无需重复操作。", ephemeral=True
                        ),
                        priority=1,
                    )
                    return

                # 执行核心业务逻辑
                await uow.moderation.update_user_validation_status(
                    user_id=self.kicked_user.id,
                    thread_id=thread.id,
                    is_valid=False,
                )

            # 创建并发送公开的处罚公示
            embed = ModerationEmbedBuilder.create_kick_embed(
                moderator=moderator,
                kicked_user=self.kicked_user,
                reason=self.reason_input.value,
                target_message=self.target_message,
            )

            await self.bot.api_scheduler.submit(thread.send(embed=embed), priority=5)

            logger.info(
                f"用户 {moderator.id} 在帖子 {thread.id} 中 "
                f"将用户 {self.kicked_user.id} 的投票资格设置为无效。"
            )

        except Exception as e:
            logger.error(f"在处理踢出提案时发生错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                modal_interaction.followup.send(
                    "处理请求时发生错误，请联系技术人员。", ephemeral=True
                ),
                priority=1,
            )
