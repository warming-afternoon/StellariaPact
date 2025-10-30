import logging
from typing import TYPE_CHECKING, Awaitable, Callable

import discord

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ObjectionFormalVoteChoiceView(discord.ui.View):
    """
    用于私密消息中的正式异议投票选择视图。
    """

    message: discord.Message | None = None
    bot: "StellariaPactBot"

    def __init__(
        self,
        bot: "StellariaPactBot",
        is_eligible: bool,
        on_agree: Callable[[discord.Interaction], Awaitable[None]],
        on_disagree: Callable[[discord.Interaction], Awaitable[None]],
        on_abstain: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=890)
        self.bot = bot
        self.on_agree_callback = on_agree
        self.on_disagree_callback = on_disagree
        self.on_abstain_callback = on_abstain

        # 根据资格禁用按钮
        if not is_eligible:
            self.agree_button.disabled = True
            self.disagree_button.disabled = True
            self.abstain_button.disabled = True

    @discord.ui.button(
        label="同意异议",
        style=discord.ButtonStyle.success,
        custom_id="objection_formal_choice_agree",
    )
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“同意”按钮点击事件，调用注入的回调。"""
        await self.on_agree_callback(interaction)

    @discord.ui.button(
        label="反对异议",
        style=discord.ButtonStyle.danger,
        custom_id="objection_formal_choice_disagree",
    )
    async def disagree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“反对”按钮点击事件，调用注入的回调。"""
        await self.on_disagree_callback(interaction)

    @discord.ui.button(
        label="弃票",
        style=discord.ButtonStyle.secondary,
        custom_id="objection_formal_choice_abstain",
    )
    async def abstain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理"弃票"按钮点击事件，调用注入的回调"""
        await self.on_abstain_callback(interaction)

    async def on_timeout(self) -> None:
        """
        当视图超时后自动调用此方法。
        """
        if self.message:  # 确保我们有消息对象
            try:
                # 删除消息
                await self.bot.api_scheduler.submit(
                    self.message.delete(),
                    priority=5,
                )
            except discord.NotFound:
                # 如果消息已被用户删除，则忽略
                pass
            except Exception as e:
                logger.error(f"删除超时的私信异议投票面板时出错: {e}")
