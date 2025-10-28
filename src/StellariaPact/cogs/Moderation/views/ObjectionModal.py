import discord

from StellariaPact.share.StellariaPactBot import StellariaPactBot


class ObjectionModal(discord.ui.Modal, title="发起异议"):
    """
    一个模态框，用于收集用户对提案发起异议所需的信息。
    """

    reason = discord.ui.TextInput(
        label="反对理由",
        placeholder="请详细阐述您反对该提案的理由。",
        required=True,
        style=discord.TextStyle.long,
    )
    proposal_link = discord.ui.TextInput(
        label="提案链接",
        placeholder="请在此处粘贴目标提案的讨论帖链接（可选，默认为当前帖子）",
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self, bot: StellariaPactBot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交模态框时，派发一个全局事件
        """

        self.bot.dispatch(
            "objection_modal_submitted",
            interaction,
            self.proposal_link.value,
            self.reason.value,
        )
