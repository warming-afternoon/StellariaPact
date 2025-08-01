from typing import Awaitable, Callable

import discord

from StellariaPact.share.StellariaPactBot import StellariaPactBot


class ConfirmationView(discord.ui.View):
    """
    一个通用的二次确认视图。
    它接收一个回调函数，在用户点击“确认”后执行。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        on_confirm_callback: Callable[[], Awaitable[None]],
        *,
        timeout: float | None = 180,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.on_confirm_callback = on_confirm_callback
        self.interaction_response: discord.InteractionMessage | None = None

    async def on_timeout(self) -> None:
        if self.interaction_response:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await self.bot.api_scheduler.submit(
                self.interaction_response.edit(content="操作已超时。", view=self),
                priority=1,
            )

    @discord.ui.button(label="确认", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 禁用所有按钮以防止重复点击
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # 更新原始消息
        await interaction.response.edit_message(content="正在处理...", view=self)

        # 执行回调
        await self.on_confirm_callback()

        # 最终确认
        await self.bot.api_scheduler.submit(
            interaction.followup.edit_message(interaction.message.id, content="操作已成功完成。"),
            priority=1,
        )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 禁用所有按钮
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(content="操作已取消。", view=self)
