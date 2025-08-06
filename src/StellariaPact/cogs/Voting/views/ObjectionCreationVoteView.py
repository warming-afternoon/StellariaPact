import logging
from typing import TYPE_CHECKING, Literal

import discord

from ....share.SafeDefer import safeDefer
from ...Moderation.qo.ObjectionSupportQo import ObjectionSupportQo
from .ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot
    from ...Moderation.ModerationLogic import ModerationLogic


logger = logging.getLogger(__name__)


class ObjectionCreationVoteView(discord.ui.View):
    """
    异议支持收集阶段的公开视图。
    """

    def __init__(self, bot: "StellariaPactBot", logic: "ModerationLogic"):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot
        self.logic = logic

    @discord.ui.button(
        label="支持此异议",
        style=discord.ButtonStyle.primary,
        custom_id="objection_creation_support",
    )
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“支持”按钮点击事件"""
        await self._handle_choice(interaction, "support")

    @discord.ui.button(
        label="撤回支持",
        style=discord.ButtonStyle.primary,
        custom_id="objection_creation_withdraw",
    )
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“撤回支持”按钮点击事件"""
        await self._handle_choice(interaction, "withdraw")

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        """
        统一处理用户的“支持”或“撤回”操作。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        if not interaction.message or not interaction.message.embeds:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到投票面板消息id，请重试。", ephemeral=True), 1
            )
            return

        try:
            # 准备QO并调用Logic层
            action: Literal["support", "withdraw"] = (
                "support" if choice == "support" else "withdraw"
            )
            qo = ObjectionSupportQo(
                userId=interaction.user.id,
                messageId=interaction.message.id,
                action=action,
            )

            if choice == "support":
                result_dto = await self.logic.handle_support_objection(qo)
            else:
                result_dto = await self.logic.handle_withdraw_support(qo)

            # 根据返回的DTO更新UI
            original_embed = interaction.message.embeds[0]
            guild_id = self.bot.config.get("guild_id")
            if not guild_id:
                raise RuntimeError("Guild ID 未在 config.json 中配置。")

            if result_dto.is_goal_reached:
                # 目标达成，更新Embed为“完成”状态，并禁用按钮
                new_embed = ObjectionVoteEmbedBuilder.create_goal_reached_embed(
                    original_embed, result_dto, int(guild_id)
                )
                # 禁用所有按钮
                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True
                # 使用更新后的View（self）编辑消息
                await self.bot.api_scheduler.submit(
                    interaction.message.edit(embed=new_embed, view=self), 2
                )
            else:
                # 目标未达成，只更新支持数
                new_embed = ObjectionVoteEmbedBuilder.update_support_embed(
                    original_embed, result_dto, int(guild_id)
                )
                await self.bot.api_scheduler.submit(interaction.message.edit(embed=new_embed), 2)

            # 根据返回的DTO提供精确的用户反馈
            feedback_messages = {
                "supported": "成功支持该异议！",
                "withdrew": "成功撤回支持。",
                "already_supported": "您已经支持过此异议了。",
                "not_supported": "您尚未支持此异议，无法撤回。",
            }
            feedback_message = feedback_messages.get(result_dto.user_action_result, "操作已处理。")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(feedback_message, ephemeral=True), 1
            )

        except (ValueError, RuntimeError) as e:
            logger.warning(f"处理异议创建投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True), 1
            )
        except Exception as e:
            logger.error(f"处理异议创建投票时发生未知错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )
