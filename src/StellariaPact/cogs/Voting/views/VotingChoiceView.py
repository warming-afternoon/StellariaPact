import logging
from typing import Any, Awaitable, Callable, Coroutine, Optional

import discord

from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.dto.VotingChoicePanelDto import VotingChoicePanelDto
from StellariaPact.cogs.Voting.qo.DeleteVoteQo import DeleteVoteQo
from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.cogs.Voting.views.AdjustTimeModal import AdjustTimeModal
from StellariaPact.cogs.Voting.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Voting.views.ReopenVoteModal import ReopenVoteModal
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils

logger = logging.getLogger(__name__)


class VotingChoiceView(discord.ui.View):
    """
    提供给合格用户进行投票选择的临时视图。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        logic: VotingLogic,
        original_message_id: int,
        thread_id: int,
        panel_data: VotingChoicePanelDto,
        can_manage: bool,
    ):
        super().__init__(timeout=890)  # 15分钟后超时
        self.bot = bot
        self.logic = logic
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
            logic=self.logic,
            thread_id=self.thread_id,
            message_id=self.original_message_id,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    async def _update_vote_panel_embed(self, vote_details: VoteDetailDto):
        """使用提供的 vote_details DTO 更新主投票面板的嵌入。"""
        try:
            thread = self.bot.get_channel(self.thread_id) or await self.bot.fetch_channel(
                self.thread_id
            )
            if not isinstance(thread, discord.Thread):
                logger.warning(f"找不到投票帖 (ID: {self.thread_id})")
                return

            # original_message_id 是公共投票面板的消息ID
            public_panel_message = await thread.fetch_message(self.original_message_id)
            clean_topic = StringUtils.clean_title(thread.name)

            new_embed = VoteEmbedBuilder.create_vote_panel_embed(
                topic=clean_topic,
                anonymous_flag=vote_details.is_anonymous,
                realtime_flag=vote_details.realtime_flag,
                notify_flag=vote_details.notify_flag,
                end_time=vote_details.end_time,
                vote_details=vote_details,
            )
            await self.bot.api_scheduler.submit(
                public_panel_message.edit(embed=new_embed), priority=2
            )
        except discord.NotFound:
            logger.warning(f"原始投票消息 (ID: {self.original_message_id}) 未找到, 跳过更新")
        except Exception as e:
            logger.error(
                f"更新投票面板 (ID: {self.original_message_id}) 时出错: {e}",
                exc_info=True,
            )

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
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=interaction.user.id,
                    message_id=self.original_message_id,
                    thread_id=self.thread_id,
                    choice=choice,
                    choice_index=choice_index,
                )
            )

            # 更新私有面板
            if interaction.message:
                # 重新获取数据以刷新整个面板
                panel_data = await self.logic.prepare_voting_choice_data(
                    interaction.user.id, self.thread_id, self.original_message_id
                )

                new_embed = VoteEmbedBuilder.create_management_panel_embed(
                    jump_url=f"https://discord.com/channels/{panel_data.guild_id}/{panel_data.thread_id}/{panel_data.message_id}",
                    panel_data=panel_data,
                )
                await interaction.edit_original_response(embed=new_embed, view=self)

            self.bot.dispatch("vote_details_updated", vote_details)
        except PermissionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"记录投票时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("记录投票时发生错误。", ephemeral=True)

    async def _abstain(self, interaction: discord.Interaction, choice_index: int):
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=interaction.user.id,
                    message_id=self.original_message_id,
                    choice_index=choice_index,
                )
            )
            # 更新私有面板
            if interaction.message:
                panel_data = await self.logic.prepare_voting_choice_data(
                    interaction.user.id, self.thread_id, self.original_message_id
                )
                new_embed = VoteEmbedBuilder.create_management_panel_embed(
                    jump_url=f"https://discord.com/channels/{panel_data.guild_id}/{panel_data.thread_id}/{panel_data.message_id}",
                    panel_data=panel_data,
                )
                await interaction.edit_original_response(embed=new_embed, view=self)

            self.bot.dispatch("vote_details_updated", vote_details)
        except Exception as e:
            logger.error(f"弃权时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("弃权时发生错误。", ephemeral=True)

    async def adjust_time_callback(self, interaction: discord.Interaction):
        """调整时间按钮的回调"""
        modal = AdjustTimeModal(
            self.bot, self.thread_id, self.logic, message_id=self.original_message_id
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    async def _post_public_announcement(self, embed: discord.Embed):
        """在原始投票帖中发送一个公开的通知 Embed"""
        try:
            thread_channel = self.bot.get_channel(self.thread_id) or await self.bot.fetch_channel(
                self.thread_id
            )

            if isinstance(thread_channel, discord.Thread):
                await self.bot.api_scheduler.submit(thread_channel.send(embed=embed), priority=3)
            else:
                logger.warning(f"无法发送公开通知，因为 ID {self.thread_id} 不是一个有效的帖子。")
        except discord.NotFound:
            logger.warning(f"无法发送公开通知，因为帖子 {self.thread_id} 未找到，可能已被删除。")
        except Exception as e:
            logger.error(f"发送公开通知到帖子 {self.thread_id} 时出错: {e}", exc_info=True)

    async def _handle_toggle_anonymous(self, interaction: discord.Interaction):
        """处理切换匿名投票的逻辑"""
        try:
            vote_details = await self.logic.toggle_anonymous(self.original_message_id)
            await self._update_vote_panel_embed(vote_details)

            embed = VoteEmbedBuilder.create_setting_changed_embed(
                setting_name="匿名投票",
                new_status="开启" if vote_details.is_anonymous else "关闭",
                changed_by=interaction.user,
            )
            await self._post_public_announcement(embed)

        except Exception as e:
            logger.error(f"处理切换匿名投票时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("切换匿名状态时发生内部错误。", ephemeral=True),
                priority=1,
            )

    async def _handle_toggle_realtime(self, interaction: discord.Interaction):
        """处理切换实时票数显示的逻辑"""
        try:
            vote_details = await self.logic.toggle_realtime(self.original_message_id)
            await self._update_vote_panel_embed(vote_details)

            embed = VoteEmbedBuilder.create_setting_changed_embed(
                setting_name="实时票数",
                new_status="开启" if vote_details.realtime_flag else "关闭",
                changed_by=interaction.user,
            )
            await self._post_public_announcement(embed)
        except Exception as e:
            logger.error(f"处理切换实时票数时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("切换实时状态时发生内部错误。", ephemeral=True),
                priority=1,
            )

    async def _create_and_send_confirmation(
        self,
        interaction: discord.Interaction,
        action_name: str,
        current_status: bool,
        handler: Callable[[discord.Interaction], Awaitable[None]],
    ):
        """创建并发送一个二次确认消息"""
        await safeDefer(interaction)
        title = f"确认切换「{action_name}」状态"
        description = (
            f"当前状态: **{'开启' if current_status else '关闭'}**\n\n你确定要切换此设置吗？"
        )
        embed = VoteEmbedBuilder.create_confirmation_embed(title, description)
        view = ConfirmationView(
            bot=self.bot,
            on_confirm_callback=handler,
        )
        message = await self.bot.api_scheduler.submit(
            interaction.followup.send(embed=embed, view=view, ephemeral=True), priority=1
        )
        view.message = message

    async def _handle_toggle_notify(self, interaction: discord.Interaction):
        """处理切换结束通知的逻辑"""
        try:
            vote_details = await self.logic.toggle_notify(self.original_message_id)
            await self._update_vote_panel_embed(vote_details)
            embed = VoteEmbedBuilder.create_setting_changed_embed(
                setting_name="投票结束通知提案委员",
                new_status="开启" if vote_details.notify_flag else "关闭",
                changed_by=interaction.user,
            )
            await self._post_public_announcement(embed)
        except Exception as e:
            logger.error(f"处理切换结束通知时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("切换通知状态时发生内部错误。", ephemeral=True),
                priority=1,
            )

    async def toggle_notify_callback(self, interaction: discord.Interaction):
        """处理“切换通知”按钮点击事件，发起二次确认"""
        _, _, is_notify = await self.logic.get_vote_flags(self.original_message_id)
        current_status = is_notify
        await self._create_and_send_confirmation(
            interaction, "投票结束通知提案委员", current_status, self._handle_toggle_notify
        )

    async def toggle_realtime_callback(self, interaction: discord.Interaction):
        """处理“切换实时”按钮点击事件，发起二次确认"""
        _, is_realtime, _ = await self.logic.get_vote_flags(self.original_message_id)
        current_status = is_realtime
        await self._create_and_send_confirmation(
            interaction, "实时票数", current_status, self._handle_toggle_realtime
        )

    async def toggle_anonymous_callback(self, interaction: discord.Interaction):
        """处理“切换匿名”按钮点击事件，发起二次确认"""
        is_anonymous, _, _ = await self.logic.get_vote_flags(self.original_message_id)
        current_status = is_anonymous
        await self._create_and_send_confirmation(
            interaction, "匿名投票", current_status, self._handle_toggle_anonymous
        )

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
