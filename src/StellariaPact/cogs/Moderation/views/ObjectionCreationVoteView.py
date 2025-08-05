import logging
from typing import TYPE_CHECKING

import discord

from StellariaPact.share.StellariaPactBot import StellariaPactBot

from ....share.SafeDefer import safeDefer
from ..dto.HandleSupportObjectionResultDto import HandleSupportObjectionResultDto
from ..qo.HandleSupportObjectionQo import HandleSupportObjectionQo

if TYPE_CHECKING:
    from ..logic.ModerationLogic import ModerationLogic


logger = logging.getLogger(__name__)


class ObjectionCreationVoteView(discord.ui.View):
    """
    用于“异议产生票”的视图。
    """

    def __init__(self, bot: StellariaPactBot, logic: "ModerationLogic"):
        super().__init__(timeout=None)
        self.bot = bot
        self.logic = logic

    @discord.ui.button(
        label="支持此异议",
        style=discord.ButtonStyle.success,
        custom_id="objection_creation_support",
    )
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理用户点击“支持此异议”按钮的事件。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("出现内部错误：无法找到原始消息。", ephemeral=True),
                priority=1,
            )
            return

        try:
            qo = HandleSupportObjectionQo(
                user_id=interaction.user.id,
                message_id=interaction.message.id,
            )
            result = await self.logic.handle_support_objection(qo)

            if not result.is_vote_recorded:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("您已经支持过此异议了。", ephemeral=True),
                    priority=1,
                )
                return

            await self._update_ui(interaction, result)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("成功支持该异议！", ephemeral=True), priority=1
            )

        except ValueError as e:
            logger.warning(f"处理投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"处理投票时发生错误: {e}\n请联系技术员", ephemeral=True
                ),
                priority=1,
            )

        except Exception as e:
            logger.error(
                f"处理投票时发生未知错误: {e}",
                exc_info=True,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"处理投票时发生未知错误{e}\n请联系技术员。", ephemeral=True
                ),
                priority=1,
            )

    @discord.ui.button(
        label="撤回支持",
        style=discord.ButtonStyle.secondary,
        custom_id="objection_creation_withdraw",
    )
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理用户点击“撤回支持”按钮的事件。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("出现内部错误：无法找到原始消息。", ephemeral=True),
                priority=1,
            )
            return

        try:
            qo = HandleSupportObjectionQo(
                user_id=interaction.user.id,
                message_id=interaction.message.id,
            )
            result = await self.logic.handle_withdraw_support(qo)

            # is_vote_recorded 在撤回逻辑中表示 “是否还存在投票记录”
            if result.is_vote_recorded:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("您尚未支持此异议，无法撤回。", ephemeral=True),
                    priority=1,
                )
                return

            await self._update_ui(interaction, result)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("成功撤回支持。", ephemeral=True), priority=1
            )

        except ValueError as e:
            logger.warning(f"处理投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"处理投票时发生错误: {e}\n请联系技术员", ephemeral=True
                ),
                priority=1,
            )

        except Exception as e:
            logger.error(
                f"处理投票时发生未知错误: {e}",
                exc_info=True,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"处理投票时发生未知错误{e}\n请联系技术员。", ephemeral=True
                ),
                priority=1,
            )

    async def _update_ui(
        self,
        interaction: discord.Interaction,
        result: HandleSupportObjectionResultDto,
    ):
        """
        根据逻辑层返回的结果更新UI（Embed和按钮状态）。
        """
        if not interaction.message:
            return

        original_embed = interaction.message.embeds[0]
        field_index = next(
            (i for i, f in enumerate(original_embed.fields) if f.name and "当前支持" in f.name),
            -1,
        )

        if field_index != -1:
            original_embed.set_field_at(
                field_index,
                name="当前支持",
                value=f"{result.votes_count} / {result.required_votes}",
                inline=True,
            )

        if result.is_goal_reached:
            original_embed.color = discord.Color.green()
            original_embed.title = "异议产生票收集完成"
            original_embed.description = "此异议已获得足够支持，即将进入正式投票阶段。"
            self.support_button.disabled = True
            self.withdraw_button.disabled = True
            self.support_button.label = "已达到目标"
            self.bot.dispatch("objection_formal_vote_initiation", result)
        else:
            # 如果从达到目标的状态撤回，需要恢复UI
            original_embed.color = discord.Color.yellow()
            original_embed.title = "异议产生票收集中"
            self.support_button.disabled = False
            self.withdraw_button.disabled = False
            self.support_button.label = "支持此异议"

        await self.bot.api_scheduler.submit(
            interaction.message.edit(embed=original_embed, view=self), priority=5
        )
