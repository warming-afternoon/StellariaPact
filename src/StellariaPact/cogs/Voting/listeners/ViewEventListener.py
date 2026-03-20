import asyncio
import logging
from typing import Literal

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
from StellariaPact.share.enums import ProposalStatus

logger = logging.getLogger(__name__)


class ViewEventListener(commands.Cog):
    """
    监听 Voting 模块内部派发的自定义事件
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
            vote_details.normal_options
            if view.option_type == 0
            else vote_details.objection_options
        )

        max_page = max(0, (len(all_options) - 1) // view.items_per_page) if all_options else 0
        page = min(view.page, max_page)
        user_votes = await self.logic.get_user_votes_dict(view.msg_id, interaction.user.id)

        refreshed_view = PaginatedManageView(
            bot=self.bot,
            interaction=interaction,
            thread_id=view.thread_id,
            msg_id=view.msg_id,
            options=all_options,
            option_type=view.option_type,
            page=page,
            ui_style=vote_details.ui_style,
            user_votes=user_votes
        )
        if hasattr(view, "message"):
            refreshed_view.message = view.message

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
            options=all_options,
            realtime_flag=vote_details.realtime_flag,
            ui_style=vote_details.ui_style,
        )

        await interaction.edit_original_response(embed=new_embed, view=refreshed_view)

    async def _resolve_context(
        self,
        interaction: discord.Interaction,
        source_type: Literal["local", "mirror"],
    ) -> tuple[int, int]:
        """
        显式解析上下文。
        local: 交互来自讨论帖。直接取当前频道和消息 ID。
        mirror: 交互来自投票频道。通过数据库根据镜像消息 ID 查回原帖信息。
        """
        if not interaction.message:
            raise ValueError("交互消息无效。")

        if source_type == "local":
            if not isinstance(interaction.channel, discord.Thread):
                 raise ValueError("此处只能在讨论帖内操作。")
            return interaction.channel.id, interaction.message.id

        if source_type == "mirror":
            async with UnitOfWork(self.bot.db_handler) as uow:
                session = await uow.vote_session.get_vote_session_by_voting_channel_message_id(
                    interaction.message.id
                )
                if not session or not session.context_thread_id or not session.context_message_id:
                    raise ValueError("无法在数据库中找到该镜像消息关联的原始投票会话。")
                return session.context_thread_id, session.context_message_id

        raise ValueError("未知的上下文来源。")

    @commands.Cog.listener()
    async def on_mirror_panel_clicked(self, interaction: discord.Interaction, action_name: str):
        """镜像面板（投票频道）点击的入口"""
        try:
            thread_id, original_msg_id = await self._resolve_context(interaction, "mirror")

            if action_name == "manage_vote":
                await self._internal_handle_manage_vote(interaction, thread_id, original_msg_id)
            elif action_name == "manage_rules":
                await self._internal_handle_manage_rules(interaction, thread_id, original_msg_id)
            elif action_name == "create_normal":
                await self._internal_handle_create_option(
                    interaction,
                    thread_id,
                    original_msg_id,
                    0,
                )
            elif action_name == "create_objection":
                await self._internal_handle_create_option(
                    interaction,
                    thread_id,
                    original_msg_id,
                    1,
                )
        except Exception as e:
            logger.error(f"镜像面板操作失败: {e}", exc_info=True)
            msg = str(e) if "无法" in str(e) else "处理镜像请求时出错。"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

    async def _internal_handle_manage_vote(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
    ):
        """逻辑：弹出分页投票管理面板"""
        vote_details = await self.logic.get_vote_details(message_id)
        user_votes = await self.logic.get_user_votes_dict(message_id, interaction.user.id)
        normal_options = vote_details.normal_options or []
        objection_options = vote_details.objection_options or []

        if not normal_options and not objection_options:
            await interaction.followup.send("当前暂无可管理的投票选项。", ephemeral=True)
            return

        jump_url = f"https://discord.com/channels/{vote_details.guild_id}/{thread_id}/{message_id}"

        # 如果有普通选项，发普通选项面板
        if normal_options:
            view = PaginatedManageView(
                self.bot,
                interaction,
                thread_id,
                message_id,
                normal_options,
                0,
                ui_style=vote_details.ui_style,
                user_votes=user_votes
            )
            embed = VoteEmbedBuilder.build_paginated_manage_embed(
                jump_url,
                0,
                normal_options,
                vote_details.realtime_flag,
                ui_style=vote_details.ui_style,
            )
            await DiscordUtils.send_private_panel(self.bot, interaction, embed=embed, view=view)

        # 如果有异议选项，间隔一会发送异议面板
        if objection_options:
            if normal_options:
                await asyncio.sleep(0.5)
            view = PaginatedManageView(
                self.bot,
                interaction,
                thread_id,
                message_id,
                objection_options,
                1,
            )
            embed = VoteEmbedBuilder.build_paginated_manage_embed(
                jump_url,
                1,
                objection_options,
                vote_details.realtime_flag,
            )
            await DiscordUtils.send_private_panel(self.bot, interaction, embed=embed, view=view)

    async def _internal_handle_manage_rules(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
    ):
        """逻辑：弹出规则管理面板"""
        can_manage = await PermissionGuard.can_manage_rules_or_options(interaction, thread_id)
        if not can_manage:
            await interaction.followup.send("你没有权限管理此投票的规则。", ephemeral=True)
            return


        vote_details = await self.logic.get_vote_details(message_id)
        jump_url = f"https://discord.com/channels/{vote_details.guild_id}/{thread_id}/{message_id}"

        view = RuleManagementView(self.bot, vote_details)
        embed = VoteEmbedBuilder.create_rule_management_embed(jump_url, vote_details)
        await DiscordUtils.send_private_panel(self.bot, interaction, embed=embed, view=view)

    async def _internal_handle_create_option(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        option_type: int,
    ):
        """逻辑：弹出创建选项 Modal"""
        can_create = await PermissionGuard.can_create_options(interaction, thread_id)
        if not can_create:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    (
                        "你没有权限为此提案创建投票选项。"
                        "需为提案人、管理组成员或本帖有效发言数 > 10。"
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    (
                        "你没有权限为此提案创建投票选项。"
                        "需为提案人、管理组成员或本帖有效发言数 > 10。"
                    ),
                    ephemeral=True,
                )
            return

        modal = CreateOptionModal(self.bot, message_id, thread_id, option_type)
        if not interaction.response.is_done():
            await interaction.response.send_modal(modal)
        else:
            # 如果 interaction 已被 defer，Modal 是发不出来的，需要特殊处理
            # 这里的镜像监听器 mirror_panel_clicked 在调用 create_normal 分支时故意不 safeDefer
            logger.warning("尝试在已响应的 Interaction 上发送 Modal。")


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
        thread_id: int,
        toggle_method_name: str,
        setting_name: str,
        rule_view: RuleManagementView
    ):
        """通用处理切换设置的逻辑"""
        try:
            # 获取旧状态
            old_vote_details = await self.logic.get_vote_details(message_id)

            # 执行数据库切换操作，获得最新的 VoteDetailDto
            toggle_method = getattr(self.logic, toggle_method_name)
            updated_vote_details = await toggle_method(message_id)

            # 构造原因字符串
            def to_text(status: bool) -> str:
                return "✅ 是" if status else "❌ 否"

            old_status_text = "未知"
            new_status_text = "未知"

            if toggle_method_name == "toggle_anonymous":
                old_status_text = to_text(old_vote_details.is_anonymous)
                new_status_text = to_text(updated_vote_details.is_anonymous)
            elif toggle_method_name == "toggle_realtime":
                old_status_text = to_text(old_vote_details.realtime_flag)
                new_status_text = to_text(updated_vote_details.realtime_flag)
            elif toggle_method_name == "toggle_notify":
                old_status_text = to_text(old_vote_details.notify_flag)
                new_status_text = to_text(updated_vote_details.notify_flag)

            reason = f"切换了 **{setting_name}** 状态：`{old_status_text}` → `{new_status_text}`"

            # 派发事件（同步更新讨论帖和镜像频道的面板），并发送变更通知 Embed
            operator = interaction.user
            self.bot.dispatch(
                "vote_settings_changed",
                thread_id,
                message_id,
                updated_vote_details,
                operator,
                reason,
                None,  # new_end_time
                None,  # old_end_time
            )

            # 原地更新私有的 RuleManagementView 面板
            if rule_view and rule_view.message:
                jump_url = (
                    f"https://discord.com/channels/{updated_vote_details.guild_id}/"
                    f"{thread_id}/{message_id}"
                )
                embed = VoteEmbedBuilder.create_rule_management_embed(
                    jump_url,
                    updated_vote_details,
                )

                await self.bot.api_scheduler.submit(
                    rule_view.message.edit(embed=embed), priority=2
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
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        rule_view: RuleManagementView,
    ):
        await self._handle_toggle_action(
            interaction,
            message_id,
            thread_id,
            "toggle_anonymous",
            "匿名投票",
            rule_view,
        )

    @commands.Cog.listener()
    async def on_vote_realtime_toggled(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        rule_view: RuleManagementView,
    ):
        await self._handle_toggle_action(
            interaction,
            message_id,
            thread_id,
            "toggle_realtime",
            "实时票数",
            rule_view,
        )

    @commands.Cog.listener()
    async def on_vote_notify_toggled(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        rule_view: RuleManagementView,
    ):
        await self._handle_toggle_action(
            interaction,
            message_id,
            thread_id,
            "toggle_notify",
            "投票结束通知",
            rule_view,
        )

    @commands.Cog.listener()
    async def on_panel_manage_vote_clicked(self, interaction: discord.Interaction):
        """讨论帖内点击『投票管理』"""
        try:
            tid, mid = await self._resolve_context(interaction, "local")
            await self._internal_handle_manage_vote(interaction, tid, mid)
        except Exception as e:
            await interaction.followup.send(str(e), ephemeral=True)

    @commands.Cog.listener()
    async def on_manage_vote_button_clicked(self, interaction: discord.Interaction):
        """兼容旧事件名，转发到新事件处理器。"""
        await self.on_panel_manage_vote_clicked(interaction)

    @commands.Cog.listener()
    async def on_panel_manage_rules_clicked(self, interaction: discord.Interaction):
        """讨论帖内点击『规则管理』"""
        try:
            tid, mid = await self._resolve_context(interaction, "local")
            await self._internal_handle_manage_rules(interaction, tid, mid)
        except Exception as e:
            await interaction.followup.send(str(e), ephemeral=True)

    @commands.Cog.listener()
    async def on_panel_create_option_clicked(
        self,
        interaction: discord.Interaction,
        option_type: int,
    ):
        """讨论帖内点击『创建普通/异议』"""
        try:
            tid, mid = await self._resolve_context(interaction, "local")
            await self._internal_handle_create_option(interaction, tid, mid, option_type)
        except Exception as e:
            # CreateOptionModal 涉及 response.send_modal，如果失败建议记录日志
            logger.error(f"发送 Modal 失败: {e}")

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
            # 获取创建者信息
            creator_id = interaction.user.id
            creator_name = interaction.user.display_name

            # 如果是异议类型，先检查提案状态是否允许创建异议
            if option_type == 1:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    proposal = await uow.proposal.get_proposal_by_thread_id(thread_id)
                    status = proposal.status if proposal else None
                if status and status == ProposalStatus.EXECUTING:
                    await interaction.followup.send(
                        "❌ 操作失败：该提案已进入**执行阶段**，根据议事规则，此时无法再发起新的异议。",
                        ephemeral=True
                    )
                    return

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 创建选项
                vote_session = await uow.vote_session.get_vote_session_with_details(message_id)
                if not vote_session or not vote_session.id:
                    raise ValueError("找不到对应的投票会话。")

                await uow.vote_option.add_option(
                    vote_session.id,
                    option_type=option_type,
                    text=text,
                    creator_id=creator_id,
                    creator_name=creator_name
                )

                all_options = await uow.vote_option.get_vote_options(vote_session.id)
                await uow.vote_session.update_vote_session_total_choices(
                    vote_session.id, len(all_options)
                )
                await uow.commit()

            # 创建异议投票时，派发事件让 Moderation 模块处理状态变更
            if option_type == 1:
                self.bot.dispatch(
                    "proposal_under_objection_requested",
                    thread_id=thread_id,
                    trigger_user_id=interaction.user.id,
                    source="voting_new_option",
                )

            # 更新面板
            vote_details = await self.logic.get_vote_details(message_id)
            self.bot.dispatch("vote_details_updated", vote_details)

            # 发送新选项创建通知的 Embed
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if thread:
                notification_embed = VoteEmbedBuilder.create_new_option_notification_embed(
                    creator=interaction.user,
                    option_type=option_type,
                    option_text=text
                )
                await self.bot.api_scheduler.submit(
                    thread.send(embed=notification_embed),
                    priority=3,
                )

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

    @commands.Cog.listener()
    async def on_vote_option_deleted_submitted(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        option_id: int,
        option_type: int,
        choice_index: int,
        option_text: str,
        reason: str,
        view: PaginatedManageView
    ):
        """处理选项创建人提出的选项删除请求。"""
        try:
            # 在数据库中软删除并获取更新后的 DTO
            vote_details = await self.logic.delete_vote_option(message_id, option_id)

            # 若删除的是异议选项，且当前已无任何异议选项，则派发事件恢复提案到 "讨论中"
            if option_type == 1 and not vote_details.objection_options:
                self.bot.dispatch(
                    "proposal_objection_cleared",
                    thread_id=thread_id,
                    trigger_user_id=interaction.user.id,
                    source="voting_option_deleted"
                )

            # 派发事件更新所有公共 UI (讨论贴及镜像通道)
            self.bot.dispatch("vote_details_updated", vote_details)

            # 刷新用户的私有管理面板
            await self._refresh_paginated_manage_panel(interaction, vote_details, view)

            # 向原帖发送一条公开的通知
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if thread:
                notification_embed = VoteEmbedBuilder.create_delete_option_notification_embed(
                    operator=interaction.user,
                    option_type=option_type,
                    choice_index=choice_index,
                    option_text=option_text,
                    reason=reason
                )
                await self.bot.api_scheduler.submit(
                    thread.send(embed=notification_embed),
                    priority=3,
                )

        except Exception as e:
            logger.error(f"删除投票选项时出错: {e}", exc_info=True)
            await interaction.followup.send("删除选项时发生内部错误。", ephemeral=True)
