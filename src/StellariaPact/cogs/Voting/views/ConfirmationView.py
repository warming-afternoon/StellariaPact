from typing import Awaitable, Callable

import discord

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot


class ConfirmationView(discord.ui.View):
    """
    一个通用的二次确认视图。
    它接收一个回调函数，在用户点击“确认”后执行。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        on_confirm_callback: Callable[[discord.Interaction], Awaitable[None]],
        *,
        timeout: float | None = 180,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.on_confirm_callback = on_confirm_callback
        self.message: discord.WebhookMessage | None = None

    async def on_timeout(self) -> None:
        if self.message and not self.is_finished():
            await self.bot.api_scheduler.submit(
                self.message.edit(content="操作已超时。", view=None),
                priority=1,
            )

    @discord.ui.button(label="确认", style=discord.ButtonStyle.red)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 立即响应，防止超时
        await safeDefer(interaction)

        # 执行核心业务逻辑
        await self.on_confirm_callback(interaction)

        # 删除这条临时的确认消息
        await self.bot.api_scheduler.submit(
            interaction.delete_original_response(),
            priority=1,
        )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.success)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction)
        await self.bot.api_scheduler.submit(
            interaction.delete_original_response(),
            priority=1,
        )
