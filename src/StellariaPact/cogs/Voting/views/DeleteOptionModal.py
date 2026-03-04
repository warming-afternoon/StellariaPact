import discord
from StellariaPact.share import StellariaPactBot, safeDefer


class DeleteOptionModal(discord.ui.Modal):
    """删除选项/异议并收集理由的弹窗"""

    reason = discord.ui.TextInput(
        label="删除理由",
        placeholder="请输入删除该选项/异议的理由...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    def __init__(
        self,
        bot: StellariaPactBot,
        message_id: int,
        thread_id: int,
        option_id: int,
        option_type: int,
        choice_index: int,
        option_text: str,
        manage_view: discord.ui.View
    ):
        title = "删除普通选项" if option_type == 0 else "删除异议选项"
        super().__init__(title=title)
        self.bot = bot
        self.message_id = message_id
        self.thread_id = thread_id
        self.option_id = option_id
        self.option_type = option_type
        self.choice_index = choice_index
        self.option_text = option_text
        self.manage_view = manage_view

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        reason_text = str(self.reason.value).strip()
        
        self.bot.dispatch(
            "vote_option_deleted_submitted",
            interaction=interaction,
            message_id=self.message_id,
            thread_id=self.thread_id,
            option_id=self.option_id,
            option_type=self.option_type,
            choice_index=self.choice_index,
            option_text=self.option_text,
            reason=reason_text,
            view=self.manage_view
        )