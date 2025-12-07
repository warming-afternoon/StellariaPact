import logging
from typing import Any, Callable, Coroutine, Optional

import discord

from StellariaPact.cogs.Voting.dto import VotingChoicePanelDto
from StellariaPact.cogs.Voting.views import (
    AdjustTimeModal,
    ConfirmationView,
    ReopenVoteModal,
    VoteEmbedBuilder,
)
from StellariaPact.share import StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class VotingChoiceView(discord.ui.View):
    """
    提供给合格用户进行投票选择的临时视图。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        original_message_id: int,
        thread_id: int,
        panel_data: VotingChoicePanelDto,
        can_manage: bool,
    ):
        super().__init__(timeout=890)  # 15分钟后超时
        self.bot = bot
        self.thread_id = thread_id
        self.original_message_id = original_message_id
        self.message: discord.Message | None = None
        self.is_vote_active = panel_data.is_vote_active

        is_disabled = not panel_data.is_eligible or not panel_data.is_vote_active

        # 动态添加投票按钮
        if panel_data.options:
            for i, option in enumerate(panel_data.options):
                approve_btn = discord.ui.Button(
                    label=f"赞成选项 {i + 1}",
                    style=discord.ButtonStyle.success,
                    row=i,
                    custom_id=f"approve_{option.choice_index}",
                    disabled=is_disabled,
                )
                reject_btn = discord.ui.Button(
                    label=f"反对选项 {i + 1}",
                    style=discord.ButtonStyle.danger,
                    row=i,
                    custom_id=f"reject_{option.choice_index}",
                    disabled=is_disabled,
                )
                abstain_btn = discord.ui.Button(
                    label="弃票",
                    style=discord.ButtonStyle.secondary,
                    row=i,
                    custom_id=f"abstain_{option.choice_index}",
                    disabled=is_disabled,
                )

                approve_btn.callback = self.create_callback(  # type: ignore
                    choice=1, choice_index=option.choice_index
                )
                reject_btn.callback = self.create_callback(  # type: ignore
                    choice=0, choice_index=option.choice_index
                )
                abstain_btn.callback = self.create_callback(  # type: ignore
                    choice=None, choice_index=option.choice_index
                )

                self.add_item(approve_btn)
                self.add_item(reject_btn)
                self.add_item(abstain_btn)
        else:
            # 如果没有提供选项，则为默认提案创建一组按钮
            approve_btn = discord.ui.Button(
                label="赞成",
                style=discord.ButtonStyle.success,
                row=0,
                custom_id="approve_1",
                disabled=is_disabled,
            )
            reject_btn = discord.ui.Button(
                label="反对",
                style=discord.ButtonStyle.danger,
                row=0,
                custom_id="reject_1",
                disabled=is_disabled,
            )
            abstain_btn = discord.ui.Button(
                label="弃票",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="abstain_1",
                disabled=is_disabled,
            )

            approve_btn.callback = self.create_callback(choice=1, choice_index=1)  # type: ignore
            reject_btn.callback = self.create_callback(choice=0, choice_index=1)  # type: ignore
            abstain_btn.callback = self.create_callback(choice=None, choice_index=1)  # type: ignore

            self.add_item(approve_btn)
            self.add_item(reject_btn)
            self.add_item(abstain_btn)

        if can_manage:
            start_row = len(panel_data.options) if panel_data.options else 1
            if self.is_vote_active:
                self._add_active_admin_buttons(start_row)
            else:
                self._add_inactive_admin_buttons(start_row)

    def _add_active_admin_buttons(self, start_row: int):
        """添加投票进行中时的管理员按钮"""
        adjust_time_button = discord.ui.Button(
            label="调整时间",
            style=discord.ButtonStyle.primary,
            custom_id="adjust_time",
            row=start_row,
        )
        adjust_time_button.callback = self.adjust_time_callback
        self.add_item(adjust_time_button)

        toggle_anonymous_button = discord.ui.Button(
            label="切换匿名",
            style=discord.ButtonStyle.primary,
            custom_id="toggle_anonymous",
            row=start_row,
        )
        toggle_anonymous_button.callback = self.toggle_anonymous_callback
        self.add_item(toggle_anonymous_button)

        toggle_realtime_button = discord.ui.Button(
            label="切换实时",
            style=discord.ButtonStyle.primary,
            custom_id="toggle_realtime",
            row=start_row,
        )
        toggle_realtime_button.callback = self.toggle_realtime_callback
        self.add_item(toggle_realtime_button)

        toggle_notify_button = discord.ui.Button(
            label="切换通知",
            style=discord.ButtonStyle.primary,
            custom_id="toggle_notify",
            row=start_row,
        )
        toggle_notify_button.callback = self.toggle_notify_callback
        self.add_item(toggle_notify_button)

    def _add_inactive_admin_buttons(self, start_row: int):
        """添加投票已结束时的管理员按钮"""
        reopen_vote_button = discord.ui.Button(
            label="重新开启投票",
            style=discord.ButtonStyle.primary,
            custom_id="reopen_vote",
            row=start_row,
        )
        reopen_vote_button.callback = self.reopen_vote_callback
        self.add_item(reopen_vote_button)

    async def reopen_vote_callback(self, interaction: discord.Interaction):
        """重新开启投票按钮的回调"""
        modal = ReopenVoteModal(
            bot=self.bot,
            thread_id=self.thread_id,
            message_id=self.original_message_id,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    def create_callback(
        self, choice: Optional[int], choice_index: int
    ) -> Callable[[discord.Interaction], Coroutine[Any, Any, None]]:
        async def callback(interaction: discord.Interaction):
            if choice is None:
                await self._abstain(interaction, choice_index)
            else:
                await self._record_vote(interaction, choice, choice_index)

        return callback

    async def _record_vote(self, interaction: discord.Interaction, choice: int, choice_index: int):
        self.bot.dispatch(
            "vote_choice_recorded",
            interaction=interaction,
            message_id=self.original_message_id,
            thread_id=self.thread_id,
            choice=choice,
            choice_index=choice_index,
            view=self,
        )

    async def _abstain(self, interaction: discord.Interaction, choice_index: int):
        self.bot.dispatch(
            "vote_choice_abstained",
            interaction=interaction,
            message_id=self.original_message_id,
            thread_id=self.thread_id,
            choice_index=choice_index,
            view=self,
        )

    async def adjust_time_callback(self, interaction: discord.Interaction):
        """调整时间按钮的回调"""
        modal = AdjustTimeModal(self.bot, self.thread_id, message_id=self.original_message_id)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

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

        # The handler will now dispatch an event
        async def on_confirm_handler(inner_interaction: discord.Interaction):
            self.bot.dispatch(
                event_name,
                interaction=inner_interaction,
                message_id=self.original_message_id,
                thread_id=self.thread_id,
            )

        view = ConfirmationView(
            bot=self.bot,
            on_confirm_callback=on_confirm_handler,
        )
        message = await self.bot.api_scheduler.submit(
            interaction.followup.send(embed=embed, view=view, ephemeral=True), priority=1
        )
        view.message = message

    async def toggle_notify_callback(self, interaction: discord.Interaction):
        """处理“切换通知”按钮点击事件，发起二次确认"""
        await self._create_and_send_confirmation(
            interaction,
            "投票结束通知提案委员",
            "vote_notify_toggled",
        )

    async def toggle_realtime_callback(self, interaction: discord.Interaction):
        """处理“切换实时”按钮点击事件，发起二次确认"""
        await self._create_and_send_confirmation(interaction, "实时票数", "vote_realtime_toggled")

    async def toggle_anonymous_callback(self, interaction: discord.Interaction):
        """处理“切换匿名”按钮点击事件，发起二次确认"""
        await self._create_and_send_confirmation(interaction, "匿名投票", "vote_anonymous_toggled")

    async def on_timeout(self) -> None:
        """
        当视图超时后自动调用此方法。
        """
        if self.message:  # 确保我们有消息对象
            try:
                # 删除消息
                await self.bot.api_scheduler.submit(
                    self.message.delete(),
                    priority=5,
                )
            except discord.NotFound:
                # 如果消息已被用户删除，则忽略
                pass
            except Exception as e:
                logger.error(f"删除超时的私信投票面板时出错: {e}")
