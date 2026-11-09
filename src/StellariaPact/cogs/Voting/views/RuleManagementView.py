import asyncio
import logging

import discord

from StellariaPact.cogs.Voting.views import AdjustTimeModal, ConfirmationView, ReopenVoteModal
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.share import PermissionGuard, StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class RuleManagementView(discord.ui.View):
    """规则管理面板：用于管理投票规则。"""

    # 用于记录自身的 message 实例，方便后续原地更新 Embed
    message: discord.Message | None = None

    PAGE_SIZE = 10

    def __init__(
        self,
        bot: StellariaPactBot,
        vote_details: VoteDetailDto,
        *,
        source_guild_id: int | None = None,
    ):
        super().__init__(timeout=900)
        self.bot = bot
        self.logic = VotingLogic(bot)
        self.source_guild_id = source_guild_id or vote_details.guild_id
        self.page = 0
        self._refresh_lock = asyncio.Lock()
        self.thread_id = vote_details.context_thread_id
        # 确保 message_id 不为 None
        self.message_id = vote_details.context_message_id or 0
        self._build_ui(vote_details)

    def build_embed(self, vote_details: VoteDetailDto) -> discord.Embed:
        """构建当前页的私有票数统计。"""
        jump_url = (
            f"https://discord.com/channels/{vote_details.guild_id}/"
            f"{self.thread_id}/{self.message_id}"
        )
        return VoteEmbedBuilder.create_rule_management_embed(
            jump_url, vote_details, self.page, self.PAGE_SIZE
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """交互前重新确认规则管理权限。"""
        if await PermissionGuard.can_manage_rules_or_options(
            interaction, self.thread_id, private_panel_guild_id=self.source_guild_id
        ):
            return True

        message = "你没有权限管理此投票的规则。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False

    async def refresh_panel(self, page_delta: int = 0) -> None:
        """重新读取投票数据并在原消息中更新当前页。"""
        async with self._refresh_lock:
            if self.message is None:
                return

            vote_details = await self.logic.get_vote_details(self.message_id)
            self._build_ui(vote_details, page_delta)
            await self.bot.api_scheduler.submit(
                self.message.edit(embed=self.build_embed(vote_details), view=self), priority=2
            )

    async def previous_page(self, interaction: discord.Interaction) -> None:
        """显示最新的上一页票数。"""
        await interaction.response.defer()
        await self.refresh_panel(-1)

    async def next_page(self, interaction: discord.Interaction) -> None:
        """显示最新的下一页票数。"""
        await interaction.response.defer()
        await self.refresh_panel(1)

    def _build_ui(self, vote_details: VoteDetailDto, page_delta: int = 0):
        """根据投票状态和当前页创建按钮。"""
        self.clear_items()

        is_closed = vote_details.status == 0
        option_count = (
            len(vote_details.normal_options) + len(vote_details.objection_options)
            or len(vote_details.options)
        )

        last_page = max(0, (option_count - 1) // self.PAGE_SIZE)
        self.page = min(max(0, self.page + page_delta), last_page)

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

        # 票数分页使用独立按钮行，已结束的投票仍可查看。
        previous = discord.ui.Button(
            label="上一页", row=3, disabled=self.page == 0, custom_id="rule_stats_previous"
        )
        previous.callback = self.previous_page
        self.add_item(previous)
        following = discord.ui.Button(
            label="下一页",
            row=3,
            disabled=(self.page + 1) * self.PAGE_SIZE >= option_count,
            custom_id="rule_stats_next",
        )
        following.callback = self.next_page
        self.add_item(following)

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
            if not await self.interaction_check(inner_interaction):
                return

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
