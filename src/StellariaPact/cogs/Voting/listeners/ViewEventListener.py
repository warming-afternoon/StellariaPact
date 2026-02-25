import asyncio
import logging

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.qo import DeleteVoteQo, RecordVoteQo
from StellariaPact.cogs.Voting.views import (
    CreateOptionModal,
    PaginatedManageView,
    RuleManagementView,
    VoteEmbedBuilder,
)
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share import (
    DiscordUtils,
    PermissionGuard,
    StellariaPactBot,
    UnitOfWork,
    safeDefer,
)
from StellariaPact.share.enums.ProposalStatus import ProposalStatus

logger = logging.getLogger(__name__)


class ViewEventListener(commands.Cog):
    """
    专门监听由 Views, Modals, 等UI组件派发的自定义事件。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

    async def _update_private_panel(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        view: discord.ui.View,
    ):
        """通用私有面板更新"""
        if interaction.message:
            panel_data = await self.logic.prepare_voting_choice_data(
                interaction.user.id, thread_id, message_id
            )
            new_embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=f"https://discord.com/channels/{panel_data.guild_id}/{panel_data.thread_id}/{panel_data.message_id}",
                panel_data=panel_data,
            )
            await interaction.edit_original_response(embed=new_embed, view=view)

    async def _refresh_paginated_manage_panel(
        self,
        interaction: discord.Interaction,
        vote_details,
        view: PaginatedManageView | None,
    ):
        """刷新分页投票管理私有面板（原地覆盖 embed + view）。"""
        if not view or not interaction.message:
            return

        all_options = (
            vote_details.normal_options if view.option_type == 0 else vote_details.objection_options
        )

        max_page = max(0, (len(all_options) - 1) // view.items_per_page) if all_options else 0
        page = min(view.page, max_page)

        refreshed_view = PaginatedManageView(
            bot=self.bot,
            interaction=interaction,
            thread_id=view.thread_id,
            msg_id=view.msg_id,
            options=all_options,
            option_type=view.option_type,
            page=page,
        )

        start_idx = page * refreshed_view.items_per_page
        page_options = all_options[start_idx : start_idx + refreshed_view.items_per_page]

        jump_url = (
            f"https://discord.com/channels/{vote_details.guild_id}/{vote_details.context_thread_id}/{vote_details.context_message_id}"
            if vote_details.guild_id
            and vote_details.context_thread_id
            and vote_details.context_message_id
            else ""
        )
        new_embed = VoteEmbedBuilder.build_paginated_manage_embed(
            jump_url=jump_url,
            option_type=view.option_type,
            options=page_options,
            realtime_flag=vote_details.realtime_flag,
        )

        await interaction.edit_original_response(embed=new_embed, view=refreshed_view)


    @commands.Cog.listener()
    async def on_vote_choice_recorded(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        choice: int,
        choice_index: int,
        view: discord.ui.View,
    ):
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=interaction.user.id,
                    message_id=message_id,
                    thread_id=thread_id,
                    choice=choice,
                    option_type=0,
                    choice_index=choice_index,
                )
            )
            await self._update_private_panel(interaction, thread_id, message_id, view)
            self.bot.dispatch("vote_details_updated", vote_details)
        except PermissionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"记录投票时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("记录投票时发生错误。", ephemeral=True)

    @commands.Cog.listener()
    async def on_vote_choice_abstained(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        choice_index: int,
        view: discord.ui.View,
    ):
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=interaction.user.id,
                    message_id=message_id,
                    option_type=0,
                    choice_index=choice_index,
                )
            )
            await self._update_private_panel(interaction, thread_id, message_id, view)
            self.bot.dispatch("vote_details_updated", vote_details)
        except Exception as e:
            logger.error(f"弃权时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("弃权时发生错误。", ephemeral=True)

    @commands.Cog.listener()
    async def on_vote_time_adjusted(
        self,
        *,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        hours_to_adjust: int,
    ):
        try:
            await self.logic.adjust_vote_time(
                thread_id=thread_id,
                message_id=message_id,
                hours_to_adjust=hours_to_adjust,
                operator=interaction.user,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票时间已成功调整。", ephemeral=True), priority=1
            )
        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True),
                priority=1,
            )

    @commands.Cog.listener()
    async def on_vote_reopened(
        self,
        *,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        hours_to_add: int,
    ):
        try:
            await self.logic.reopen_vote(
                thread_id=thread_id,
                message_id=message_id,
                hours_to_add=hours_to_add,
                operator=interaction.user,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票已重新开启。", ephemeral=True), priority=1
            )
        except Exception as e:
            logger.error(f"重新开启投票时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True),
                priority=1,
            )

    async def _handle_toggle_action(
        self,
        interaction: discord.Interaction,
        message_id: int,
        toggle_method_name: str,
        setting_name: str,
    ):
        """通用处理切换设置的逻辑"""
        await safeDefer(interaction, ephemeral=True)
        try:
            toggle_method = getattr(self.logic, toggle_method_name)
            await toggle_method(message_id, operator=interaction.user)

            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"已成功切换 **{setting_name}** 状态。", ephemeral=True),
                priority=1,
            )
        except Exception as e:
            logger.error(f"处理切换 {setting_name} 时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"切换 {setting_name} 状态时发生内部错误。", ephemeral=True
                ),
                priority=1,
            )

    @commands.Cog.listener()
    async def on_vote_anonymous_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_anonymous", "匿名投票")

    @commands.Cog.listener()
    async def on_vote_realtime_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_realtime", "实时票数")

    @commands.Cog.listener()
    async def on_vote_notify_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_notify", "投票结束通知")

    @commands.Cog.listener()
    async def on_panel_manage_vote_clicked(self, interaction: discord.Interaction):
        """处理主面板“投票管理”按钮，分别发普通/异议分页面板。"""
        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True)
            return

        if not interaction.message:
            await interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True)
            return

        try:
            vote_details = await self.logic.get_vote_details(interaction.message.id)

            normal_options = vote_details.normal_options or []
            objection_options = vote_details.objection_options or []

            if not normal_options and not objection_options:
                await interaction.followup.send("当前暂无可管理的投票选项。", ephemeral=True)
                return

            if normal_options:
                normal_view = PaginatedManageView(
                    bot=self.bot,
                    interaction=interaction,
                    thread_id=interaction.channel.id,
                    msg_id=interaction.message.id,
                    options=normal_options,
                    option_type=0,
                    page=0,
                )
                jump_url = (
                    f"https://discord.com/channels/{vote_details.guild_id}/{vote_details.context_thread_id}/{vote_details.context_message_id}"
                    if vote_details.guild_id
                    and vote_details.context_thread_id
                    and vote_details.context_message_id
                    else ""
                )
                normal_embed = VoteEmbedBuilder.build_paginated_manage_embed(
                    jump_url=jump_url,
                    option_type=0,
                    options=normal_options,
                    realtime_flag=vote_details.realtime_flag,
                )
                await DiscordUtils.send_private_panel(
                    self.bot,
                    interaction,
                    embed=normal_embed,
                    view=normal_view,
                )
                if objection_options:
                    await asyncio.sleep(0.5)

            if objection_options:
                objection_view = PaginatedManageView(
                    bot=self.bot,
                    interaction=interaction,
                    thread_id=interaction.channel.id,
                    msg_id=interaction.message.id,
                    options=objection_options,
                    option_type=1,
                    page=0,
                )
                jump_url = (
                    f"https://discord.com/channels/{vote_details.guild_id}/{vote_details.context_thread_id}/{vote_details.context_message_id}"
                    if vote_details.guild_id
                    and vote_details.context_thread_id
                    and vote_details.context_message_id
                    else ""
                )
                objection_embed = VoteEmbedBuilder.build_paginated_manage_embed(
                    jump_url=jump_url,
                    option_type=1,
                    options=objection_options,
                    realtime_flag=vote_details.realtime_flag,
                )
                await DiscordUtils.send_private_panel(
                    self.bot,
                    interaction,
                    embed=objection_embed,
                    view=objection_view,
                )

        except Exception as e:
            logger.error(f"处理投票管理面板时出错: {e}", exc_info=True)
            await interaction.followup.send(f"处理投票管理面板时出错: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_manage_vote_button_clicked(self, interaction: discord.Interaction):
        """兼容旧事件名，转发到新事件处理器。"""
        await self.on_panel_manage_vote_clicked(interaction)

    @commands.Cog.listener()
    async def on_panel_manage_rules_clicked(self, interaction: discord.Interaction):
        """处理主面板“规则管理”按钮。"""
        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True)
            return

        if not interaction.message:
            await interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True)
            return

        can_manage = await PermissionGuard.can_manage_rules_or_options(interaction)
        if not can_manage:
            await interaction.followup.send("你没有权限管理规则。", ephemeral=True)
            return

        try:
            anonymous_flag, realtime_flag, notify_flag = await self.logic.get_vote_flags(
                interaction.message.id
            )
            view = RuleManagementView(
                bot=self.bot,
                thread_id=interaction.channel.id,
                message_id=interaction.message.id,
            )
            embed = discord.Embed(title="规则管理", color=discord.Color.blue())
            embed.add_field(name="匿名投票", value="✅ 是" if anonymous_flag else "❌ 否", inline=True)
            embed.add_field(name="实时票数", value="✅ 是" if realtime_flag else "❌ 否", inline=True)
            embed.add_field(name="结束通知", value="✅ 是" if notify_flag else "❌ 否", inline=True)
            await DiscordUtils.send_private_panel(self.bot, interaction, embed=embed, view=view)
        except Exception as e:
            logger.error(f"处理规则管理面板时出错: {e}", exc_info=True)
            await interaction.followup.send("处理规则管理面板时出错。", ephemeral=True)

    @commands.Cog.listener()
    async def on_panel_create_option_clicked(self, interaction: discord.Interaction, option_type: int):
        """处理主面板“创建普通投票/创建异议”按钮。"""
        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True)
            return

        if not interaction.message:
            await interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True)
            return

        can_manage = await PermissionGuard.can_manage_rules_or_options(interaction)
        if not can_manage:
            await interaction.followup.send("你没有权限创建投票选项。", ephemeral=True)
            return

        modal = CreateOptionModal(
            bot=self.bot,
            message_id=interaction.message.id,
            thread_id=interaction.channel.id,
            option_type=option_type,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    @commands.Cog.listener()
    async def on_new_option_submitted(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        option_type: int,
        option_text: str,
    ):
        """处理新增选项提交。"""
        text = option_text.strip()
        if not text:
            await interaction.followup.send("选项内容不能为空。", ephemeral=True)
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                vote_session = await uow.vote_session.get_vote_session_with_details(message_id)
                if not vote_session or not vote_session.id:
                    raise ValueError("找不到对应的投票会话。")

                await uow.vote_option.add_option(vote_session.id, option_type=option_type, text=text)
                all_options = await uow.vote_option.get_vote_options(vote_session.id)
                await uow.vote_session.update_vote_session_total_choices(
                    vote_session.id, len(all_options)
                )

                if option_type == 1:
                    await uow.proposal.update_proposal_status_by_thread_id(
                        thread_id, ProposalStatus.UNDER_OBJECTION
                    )

                await uow.commit()

            vote_details = await self.logic.get_vote_details(message_id)
            self.bot.dispatch("vote_details_updated", vote_details)
            await interaction.followup.send("已成功创建新投票选项。", ephemeral=True)
        except Exception as e:
            logger.error(f"创建新选项时出错: {e}", exc_info=True)
            await interaction.followup.send("创建新选项时发生错误。", ephemeral=True)

    @commands.Cog.listener()
    async def on_user_vote_submitted(
        self,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        option_type: int,
        choice_index: int,
        choice: int | None,
        view: PaginatedManageView | None = None,
    ):
        """处理分页管理视图投票提交。"""
        try:
            if choice is None:
                vote_details = await self.logic.delete_vote_and_get_details(
                    DeleteVoteQo(
                        user_id=interaction.user.id,
                        message_id=message_id,
                        option_type=option_type,
                        choice_index=choice_index,
                    )
                )
            else:
                vote_details = await self.logic.record_vote_and_get_details(
                    RecordVoteQo(
                        user_id=interaction.user.id,
                        message_id=message_id,
                        thread_id=thread_id,
                        choice=choice,
                        option_type=option_type,
                        choice_index=choice_index,
                    )
                )

            self.bot.dispatch("vote_details_updated", vote_details)
            await self._refresh_paginated_manage_panel(interaction, vote_details, view)
        except PermissionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"提交分页管理投票时出错: {e}", exc_info=True)
            await interaction.followup.send("提交投票时发生错误。", ephemeral=True)
