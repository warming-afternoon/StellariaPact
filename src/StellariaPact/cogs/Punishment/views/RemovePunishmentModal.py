import discord

from StellariaPact.share import StellariaPactBot, safeDefer


class RemovePunishmentModal(discord.ui.Modal):
    def __init__(self, bot: StellariaPactBot, target_user: discord.User | discord.Member):
        super().__init__(title="解除提案处罚理由", timeout=1000)
        self.bot = bot
        self.target_user = target_user

        self.reason = discord.ui.TextInput(
            label="解除理由",
            style=discord.TextStyle.long,
            placeholder="请输入解除该用户此处罚的原因...",
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        # 派发事件，由监听器捕获并处理业务
        self.bot.dispatch(
            "punishment_remove_request",
            interaction,
            interaction.channel,     # thread
            interaction.user,        # moderator
            self.target_user,
            self.reason.value
        )
        await interaction.followup.send("请求已提交，正在处理中...", ephemeral=True)
