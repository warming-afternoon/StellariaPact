import discord

from ....cogs.Moderation.qo.EditObjectionReasonQo import EditObjectionReasonQo
from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot


class EditObjectionReasonModal(discord.ui.Modal):
    """
    一个模态框，允许异议发起人编辑他们的异议理由。
    """

    reason_input = discord.ui.TextInput(
        label="新的异议理由",
        style=discord.TextStyle.paragraph,
        placeholder="请详细说明您更新后的异议理由...",
        required=True,
        max_length=4000,
    )

    def __init__(self, bot: StellariaPactBot, objection_id: int):
        super().__init__(title="编辑异议理由")
        self.bot = bot
        self.objection_id = objection_id

    async def on_submit(self, interaction: discord.Interaction):
        """
        处理提交事件，分派一个带有QO的事件。
        """
        # 立即响应用户，告知请求已收到
        await safeDefer(interaction, ephemeral=True)

        new_reason = self.reason_input.value

        # 创建查询对象
        qo = EditObjectionReasonQo(
            interaction=interaction,
            objection_id=self.objection_id,
            new_reason=new_reason,
        )

        # 分派事件，交由监听器处理
        self.bot.dispatch("edit_objection_reason_submitted", qo)
