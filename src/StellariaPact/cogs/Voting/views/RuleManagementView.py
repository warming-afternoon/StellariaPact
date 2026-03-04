import logging

import discord
from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.cogs.Voting.views import AdjustTimeModal, ConfirmationView, ReopenVoteModal
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.share import StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class RuleManagementView(discord.ui.View):
    """规则管理面板：用于管理投票规则。"""

    # 用于记录自身的 message 实例，方便后续原地更新 Embed
    message: discord.Message | None = None

    def __init__(self, bot: StellariaPactBot, vote_details: VoteDetailDto):
        super().__init__(timeout=900)
        self.bot = bot
        self.vote_details = vote_details
        self.thread_id = vote_details.context_thread_id
        # 确保 message_id 不为 None
        self.message_id = vote_details.context_message_id or 0
        self._build_ui(vote_details)

    def _build_ui(self, vote_details: VoteDetailDto):
        """根据投票状态创建按钮。"""
        self.clear_items()

        is_closed = (vote_details.status == 0)

        # 第一行
        btn_anonymous = discord.ui.Button(
            label="匿名投票",
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id="rule_manage_anonymous",
            disabled=is_closed,
        )
        btn_anonymous.callback = self.toggle_anonymous
        self.add_item(btn_anonymous)

        btn_realtime = discord.ui.Button(
            label="实时票数",
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id="rule_manage_realtime",
            disabled=is_closed,
        )
        btn_realtime.callback = self.toggle_realtime
        self.add_item(btn_realtime)

        btn_notify = discord.ui.Button(
            label="结束投票时通知提案组",
            style=discord.ButtonStyle.primary,
            row=0,
            custom_id="rule_manage_notify",
            disabled=is_closed,
        )
        btn_notify.callback = self.toggle_notify
        self.add_item(btn_notify)

        # 第二行
        btn_adjust_time = discord.ui.Button(
            label="调整时间",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="rule_manage_adjust_time",
            disabled=is_closed,
        )
        btn_adjust_time.callback = self.adjust_time
        self.add_item(btn_adjust_time)

        # 第三行：仅在已结束时出现
        if is_closed:
            reopen_btn = discord.ui.Button(
                label="重新开启投票",
                style=discord.ButtonStyle.danger,
                row=2,
                custom_id="rule_manage_reopen_vote",
            )
            reopen_btn.callback = self.reopen_vote_callback
            self.add_item(reopen_btn)

    async def reopen_vote_callback(self, interaction: discord.Interaction):
        """重新开启投票按钮的回调"""
        modal = ReopenVoteModal(
            bot=self.bot,
            thread_id=self.thread_id,
            message_id=self.message_id,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    async def on_timeout(self) -> None:
        """
        当视图超时后自动调用此方法。
        """
        if self.message:
            try:
                await self.bot.api_scheduler.submit(
                    self.message.delete(),
                    priority=5,
                )
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error(f"删除超时的规则管理面板时出错: {e}")

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

    async def toggle_anonymous(self, interaction: discord.Interaction):
        await self._create_and_send_confirmation(interaction, "匿名投票", "vote_anonymous_toggled")

    async def toggle_realtime(self, interaction: discord.Interaction):
        await self._create_and_send_confirmation(interaction, "实时票数", "vote_realtime_toggled")

    async def toggle_notify(self, interaction: discord.Interaction):
        await self._create_and_send_confirmation(
            interaction,
            "结束投票时通知提案组",
            "vote_notify_toggled",
        )

    async def adjust_time(self, interaction: discord.Interaction):
        modal = AdjustTimeModal(self.bot, self.thread_id, self.message_id)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
