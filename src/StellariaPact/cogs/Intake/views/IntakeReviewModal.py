import discord
from discord.ui import Modal, TextInput

from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeReviewModal(Modal):
    """
    审核意见收集模态框
    """

    def __init__(self, bot: "StellariaPactBot", action: str):
        self.bot = bot
        self.action = action
        action_text = {
            "approved": "批准",
            "rejected": "拒绝",
            "modification_requested": "要求修改",
        }[action]
        super().__init__(title=f"草案{action_text} - 填写审核意见")

        self.review_comment = TextInput(
            label="审核意见",
            style=discord.TextStyle.paragraph,
            placeholder="请填写您的审核意见...",
            required=True,
            max_length=2000,
        )
        self.add_item(self.review_comment)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # 分发事件，包含审核意见
        self.bot.dispatch(f"intake_{self.action}", interaction, self.review_comment.value)
