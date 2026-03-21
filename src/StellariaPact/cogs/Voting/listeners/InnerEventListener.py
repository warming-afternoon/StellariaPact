import asyncio
import logging
from datetime import datetime
from typing import Literal

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.cogs.Voting.qo import DeleteVoteQo, RecordVoteQo
from StellariaPact.cogs.Voting.views import (
    CreateOptionModal,
    PaginatedManageView,
    RuleManagementView,
    VoteEmbedBuilder,
    VoteView,
    VotingChannelView,
)
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import ProposalDto, VoteMessageMirrorDto, VoteSessionDto
from StellariaPact.share import (
    DiscordUtils,
    PermissionGuard,
    StellariaPactBot,
    StringUtils,
    UnitOfWork,
    safeDefer,
)
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.enums import ProposalStatus

logger = logging.getLogger(__name__)


class InnerEventListener(commands.Cog):
    """
    监听 Voting 模块内部派发的自定义事件
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

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
            await self._update_private_management_panel(
                interaction=interaction,
                thread_id=thread_id,
                message_id=message_id,
                view=view,
                vote_details=vote_details,
                option_type=0,
            )
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
            await self._update_private_management_panel(
                interaction=interaction,
                thread_id=thread_id,
                message_id=message_id,
                view=view,
                vote_details=vote_details,
                option_type=0,
            )
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

    @commands.Cog.listener()
    async def on_vote_finished(self, session: "VoteSessionDto", result: "VoteDetailDto"):
        """
        监听通用投票结束事件，并发送最终结果。
        """
        try:
            thread = await DiscordUtils.fetch_thread(self.bot, session.context_thread_id)
            if not thread:
                logger.warning(f"无法为投票会话 {session.id} 找到有效的帖子。")
                return

            topic = StringUtils.clean_title(thread.name)

            jump_url = None
            if session.context_message_id:
                jump_url = f"https://discord.com/channels/{thread.guild.id}/{thread.id}/{session.context_message_id}"

            logger.info(f"投票会话 {session.id} 结束，生成跳转链接: {jump_url}")

            # 构建主结果 Embeds (包含普通投票和异议投票结果)
            result_embeds = VoteEmbedBuilder.build_vote_result_embeds(
                topic, result, jump_url=jump_url
            )

            all_embeds_to_send = result_embeds

            # 如果不是匿名投票，则构建并添加各选项的投票者名单
            if not result.is_anonymous and result.voters:
                voter_embeds = VoteEmbedBuilder.build_voter_list_embeds_from_details(result)
                all_embeds_to_send.extend(voter_embeds)

            # 准备要@的身份组
            content_to_send = ""
            if result.notify_flag:
                council_role_id = self.bot.config.get("roles", {}).get("councilModerator")
                auditor_role_id = self.bot.config.get("roles", {}).get("executionAuditor")
                mentions = []
                if council_role_id:
                    mentions.append(f"<@&{council_role_id}>")
                if auditor_role_id:
                    mentions.append(f"<@&{auditor_role_id}>")
                if mentions:
                    content_to_send = " ".join(mentions)

            # 分批发送所有 Embeds
            # Discord 一次最多发送 10 个 embeds
            for i in range(0, len(all_embeds_to_send), 10):
                chunk = all_embeds_to_send[i : i + 10]
                # 只在第一条消息中添加 content
                if i == 0 and content_to_send:
                    await self.bot.api_scheduler.submit(
                        thread.send(content=content_to_send, embeds=chunk),
                        priority=5,
                    )
                else:
                    await self.bot.api_scheduler.submit(
                        thread.send(embeds=chunk),
                        priority=5,
                    )
        except Exception as e:
            logger.error(
                f"处理 'on_vote_finished' 事件时出错 (会话ID: {session.id}): {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_vote_settings_changed(
        self,
        thread_id: int,
        message_id: int,
        vote_details: VoteDetailDto,
        operator: discord.User | discord.Member,
        reason: str,
        new_end_time: datetime | None = None,
        old_end_time: datetime | None = None,
    ):
        """
        监听投票设置变更事件，统一处理UI更新。
        """
        try:
            # 统一派发详情更新事件，让 on_vote_details_updated 处理所有面板更新
            self.bot.dispatch("vote_details_updated", vote_details)

            # 发送公开通知
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if thread:
                notification_embed = VoteEmbedBuilder.create_settings_changed_notification_embed(
                    operator=operator,
                    reason=reason,
                    new_end_time=new_end_time,
                    old_end_time=old_end_time,
                )
                await self.bot.api_scheduler.submit(
                    thread.send(embed=notification_embed), priority=3
                )

        except Exception as e:
            logger.error(
                f"处理 'on_vote_settings_changed' 事件时出错 (消息ID: {message_id}): {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_vote_details_updated(self, vote_details: VoteDetailDto):
        """当投票详情更新时，同步所有相关的投票面板。"""
        try:
            if vote_details.context_message_id is None:
                return

            thread = await DiscordUtils.fetch_thread(self.bot, vote_details.context_thread_id)
            if not thread:
                logger.warning(
                    f"找不到投票 {vote_details.context_message_id} 所在的帖子，跳过更新。"
                )
                return

            await self._update_thread_panel(thread, vote_details)

            await self._update_extra_mirrors(vote_details, thread.name)

            voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
            if not voting_channel_id_str:
                return

            channel = await DiscordUtils.fetch_channel(self.bot, int(voting_channel_id_str))
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"投票频道 {voting_channel_id_str} 不是文本频道。")
                return

            await self._update_voting_channel_panel(channel, thread, vote_details)

        except Exception as e:
            logger.error(f"同步投票面板时出错: {e}", exc_info=True)

    # -------------------------
    # 私有辅助方法
    # -------------------------

    async def _resolve_context(
        self,
        interaction: discord.Interaction,
        source_type: Literal["local", "mirror"],
    ) -> tuple[int, int]:
        """
        显式解析上下文。
        local: 交互来自讨论帖。直接取当前频道和消息 ID。
        mirror: 交互来自投票频道或额外镜像。通过数据库根据消息 ID 查回原帖信息。
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
                if not session:
                    session = await uow.vote_session.get_vote_session_by_mirror_message_id(
                        interaction.message.id
                    )
                if not session or not session.context_thread_id or not session.context_message_id:
                    raise ValueError("无法在数据库中找到该镜像消息关联的原始投票会话。")
                return session.context_thread_id, session.context_message_id

        raise ValueError("未知的上下文来源。")

    async def _internal_handle_manage_vote(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
    ):
        """弹出分页投票管理面板"""
        vote_details = await self.logic.get_vote_details(message_id)
        user_votes = await self.logic.get_user_votes_dict(message_id, interaction.user.id)
        normal_options = vote_details.normal_options or []
        objection_options = vote_details.objection_options or []

        if not normal_options and not objection_options:
            await interaction.followup.send("当前暂无可管理的投票选项。", ephemeral=True)
            return

        jump_url = f"https://discord.com/channels/{vote_details.guild_id}/{thread_id}/{message_id}"

        # 检查用户是否具有社区建设者身份组
        has_builder_role = RoleGuard.hasRoles(interaction, "communityBuilder")

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
                user_votes=user_votes,
                user_has_builder_role=has_builder_role
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
                user_has_builder_role=has_builder_role
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
        """弹出规则管理面板"""
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
        """弹出创建选项 Modal"""
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

    # -------------------------
    # 辅助方法 - 更新投票面板
    # -------------------------

    async def _refresh_paginated_manage_panel(
        self,
        interaction: discord.Interaction,
        vote_details: VoteDetailDto,
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
            user_votes=user_votes,
            user_has_builder_role=view.user_has_builder_role
        )
        if hasattr(view, "message"):
            refreshed_view.message = view.message

        await self._update_private_management_panel(
            interaction=interaction,
            thread_id=view.thread_id,
            message_id=view.msg_id,
            view=refreshed_view,
            vote_details=vote_details,
            option_type=view.option_type,
        )

    async def _update_private_management_panel(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        view: discord.ui.View | None = None,
        vote_details: VoteDetailDto | None = None,
        option_type: int = 0,
    ):
        """
        辅助方法：更新私有投票管理面板
        """
        if not interaction.message:
            return

        try:
            guild_id = vote_details.guild_id if vote_details else interaction.guild_id
            jump_url = f"https://discord.com/channels/{guild_id}/{thread_id}/{message_id}"

            # 构建 embed
            if vote_details:
                all_options = (
                    vote_details.normal_options
                    if option_type == 0
                    else vote_details.objection_options
                )
            else:
                # 如果没有提供 vote_details，需要获取
                vote_details = await self.logic.get_vote_details(message_id)
                all_options = (
                    vote_details.normal_options
                    if option_type == 0
                    else vote_details.objection_options
                )

            embed = VoteEmbedBuilder.build_paginated_manage_embed(
                jump_url=jump_url,
                option_type=option_type,
                options=all_options,
                realtime_flag=vote_details.realtime_flag,
                ui_style=vote_details.ui_style,
            )

            if view is not None:
                await self.bot.api_scheduler.submit(
                    interaction.edit_original_response(embeds=[embed], view=view),
                    priority=1
                )
            else:
                await self.bot.api_scheduler.submit(
                    interaction.edit_original_response(embeds=[embed]),
                    priority=1
                )
        except Exception as e:
            logger.warning(f"更新私有面板时出错: {e}")

    async def _update_thread_panel(self, thread: discord.Thread, vote_details: VoteDetailDto):
        """辅助方法：更新帖子内的投票面板。"""
        if not vote_details.context_message_id:
            return

        try:
            message = await thread.fetch_message(vote_details.context_message_id)

            clean_topic = StringUtils.clean_title(thread.name)
            new_embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=clean_topic,
                vote_details=vote_details,
            )

            view = VoteView(self.bot, vote_details=vote_details)

            if new_embeds:
                await self.bot.api_scheduler.submit(message.edit(embeds=new_embeds, view=view), priority=2)
        except discord.NotFound:
            logger.warning(f"找不到帖子内投票消息 {vote_details.context_message_id}，跳过更新。")
        except Exception as e:
            logger.error(f"更新帖子投票面板时出错: {e}", exc_info=True)

    async def _update_voting_channel_panel(
        self,
        channel: discord.TextChannel,
        thread: discord.Thread | None,
        vote_details: VoteDetailDto,
    ):
        """辅助方法：更新投票频道内的面板。"""
        if not vote_details.voting_channel_message_id:
            return

        try:
            message = await channel.fetch_message(vote_details.voting_channel_message_id)

            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal = await uow.proposal.get_proposal_by_thread_id(
                    vote_details.context_thread_id
                )
                if proposal and thread:
                    proposal_dto = ProposalDto.model_validate(proposal)
                    new_embeds = VoteEmbedBuilder.build_voting_channel_embed(
                        proposal_dto, vote_details, thread.jump_url
                    )

            view = VotingChannelView(self.bot, vote_details=vote_details)

            if new_embeds:
                await self.bot.api_scheduler.submit(message.edit(embeds=new_embeds, view=view), priority=2)
        except discord.NotFound:
            logger.warning(
                f"找不到投票频道内消息 {vote_details.voting_channel_message_id}，跳过更新。"
            )
        except Exception as e:
            logger.error(f"更新投票频道面板时出错: {e}", exc_info=True)

    async def _update_extra_mirrors(self, vote_details: VoteDetailDto, topic: str):
        """辅助方法：更新所有通过右键额外复制出的镜像面板"""
        if not vote_details.context_message_id:
            return


        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.vote_session.get_vote_session_by_context_message_id(vote_details.context_message_id)
            if not session or not session.id:
                return
            mirrors = await uow.vote_session.get_mirrors_by_session_id(session.id)
            mirror_dtos = [VoteMessageMirrorDto.model_validate(mirror) for mirror in mirrors]

        if not mirror_dtos:
            return

        for mirror in mirror_dtos:
            try:
                channel = await DiscordUtils.fetch_channel(self.bot, mirror.channel_id)
                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    continue
                msg = await channel.fetch_message(mirror.message_id)

                new_embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(topic, vote_details)
                view = VotingChannelView(self.bot, vote_details=vote_details)

                await self.bot.api_scheduler.submit(msg.edit(embeds=new_embeds, view=view), priority=3)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                logger.warning(f"由于权限问题，无法更新镜像消息 {mirror.message_id}。")
            except Exception as e:
                logger.error(f"更新额外镜像面板时出错: {e}", exc_info=True)

