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

    def __init__(self, bot: StellariaPactBot, proposal_link: str | None = None):
        super().__init__()
        self.bot = bot
        if proposal_link:
            self.set_proposal_link(proposal_link)

    def set_proposal_link(self, proposal_link: str) -> None:
        """
        设置提案链接的默认值
        
        Args:
            proposal_link: 提案链接URL
        """
        if not isinstance(proposal_link, str):
            raise TypeError("proposal_link 必须是字符串类型")
        if proposal_link and not proposal_link.startswith(('http://', 'https://')):
            raise ValueError("proposal_link 必须是有效的URL")
        
        self.proposal_link.default = proposal_link

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
