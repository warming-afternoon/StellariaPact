import discord

from StellariaPact.cogs.Voting.views.AdjustTimeModal import AdjustTimeModal
from StellariaPact.cogs.Voting.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.share import StellariaPactBot, safeDefer


class RuleManagementView(discord.ui.View):
    """规则管理面板：用于管理投票规则。"""

    # 用于记录自身的 message 实例，方便后续原地更新 Embed
    message: discord.Message | None = None

    def __init__(self, bot: StellariaPactBot, thread_id: int, message_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.thread_id = thread_id
        self.message_id = message_id

    async def _create_and_send_confirmation(
        self,
        interaction: discord.Interaction,
        action_name: str,
        event_name: str,
    ):
        """创建并发送一个二次确认消息，并在确认后派发事件"""
        await safeDefer(interaction)
        title = f"确认切换「{action_name}」状态"
        description = f"你确定要切换 **{action_name}** 设置吗？"
        embed = VoteEmbedBuilder.create_confirmation_embed(title, description)

        async def on_confirm_handler(inner_interaction: discord.Interaction):
            # 将当前视图自身 (rule_view=self) 传递出去，方便监听器拿到它并更新
            self.bot.dispatch(
                event_name,
                interaction=inner_interaction,
                message_id=self.message_id,
                thread_id=self.thread_id,
                rule_view=self,
            )

        view = ConfirmationView(
            bot=self.bot,
            on_confirm_callback=on_confirm_handler,
        )
        # 发送临时的确认消息
        message = await self.bot.api_scheduler.submit(
            interaction.followup.send(embed=embed, view=view, ephemeral=True), priority=1
        )
        view.message = message

    @discord.ui.button(label="匿名投票", style=discord.ButtonStyle.primary, row=0)
    async def toggle_anonymous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_and_send_confirmation(interaction, "匿名投票", "vote_anonymous_toggled")

    @discord.ui.button(label="实时票数", style=discord.ButtonStyle.primary, row=0)
    async def toggle_realtime(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_and_send_confirmation(interaction, "实时票数", "vote_realtime_toggled")

    @discord.ui.button(label="结束投票时通知提案组", style=discord.ButtonStyle.primary, row=0)
    async def toggle_notify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_and_send_confirmation(interaction, "结束投票时通知提案组", "vote_notify_toggled")

    @discord.ui.button(label="调整时间", style=discord.ButtonStyle.secondary, row=1)
    async def adjust_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AdjustTimeModal(self.bot, self.thread_id, self.message_id)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
