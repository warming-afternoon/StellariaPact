import discord

from StellariaPact.share import StellariaPactBot, safeDefer


class CreateOptionModal(discord.ui.Modal):
    """创建普通/异议投票选项的弹窗。"""

    def __init__(self, bot: StellariaPactBot, message_id: int, thread_id: int, option_type: int):
        title = "创建普通投票" if option_type == 0 else "创建异议"
        super().__init__(title=title)
        self.bot = bot
        self.message_id = message_id
        self.thread_id = thread_id
        self.option_type = option_type

        self.option_text = discord.ui.TextInput(
            label="选项内容",
            placeholder="请输入投票选项内容",
            required=True,
            max_length=200,
        )
        self.add_item(self.option_text)

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        option_text = str(self.option_text.value).strip()
        self.bot.dispatch(
            "new_option_submitted",
            interaction=interaction,
            message_id=self.message_id,
            thread_id=self.thread_id,
            option_type=self.option_type,
            option_text=option_text,
        )
