import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord.ext import commands

from StellariaPact.cogs.Moderation.qo.ObjectionSupportQo import \
    ObjectionSupportQo
from StellariaPact.cogs.Voting.views.ObjectionVoteEmbedBuilder import \
    ObjectionVoteEmbedBuilder

from ....cogs.Moderation.dto.CollectionExpiredResultDto import \
    CollectionExpiredResultDto
from ....cogs.Moderation.dto.HandleSupportObjectionResultDto import \
    HandleSupportObjectionResultDto
from ....cogs.Moderation.dto.ObjectionVotePanelDto import ObjectionVotePanelDto
from ....cogs.Moderation.qo.BuildAdminReviewEmbedQo import \
    BuildAdminReviewEmbedQo
from ....cogs.Moderation.qo.BuildFirstObjectionEmbedQo import \
    BuildFirstObjectionEmbedQo
from ....cogs.Moderation.qo.BuildProposalFrozenEmbedQo import \
    BuildProposalFrozenEmbedQo
from ....cogs.Moderation.qo.EditObjectionReasonQo import EditObjectionReasonQo
from ....cogs.Moderation.views.ModerationEmbedBuilder import \
    ModerationEmbedBuilder
from ....cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from ....cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from ....share.DiscordUtils import DiscordUtils
from ....share.StringUtils import StringUtils
from ....share.UnitOfWork import UnitOfWork
from ..ModerationLogic import ModerationLogic
from ..views.ObjectionCreationVoteView import ObjectionCreationVoteView

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ModerationListener(commands.Cog):
    """
    专门用于监听与议事管理模块相关的内部和外部事件。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)

    @commands.Cog.listener()
    async def on_proposal_thread_created(self, thread_id: int, proposer_id: int, title: str):
        """
        监听由 Voting cog 分派的提案帖子创建事件。
        """
        logger.debug(
            f"接收到提案创建事件，帖子ID: {thread_id}, 发起人ID: {proposer_id}, 标题: {title}"
        )
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.create_proposal(
                    thread_id=thread_id, proposer_id=proposer_id, title=title
                )
                await uow.commit()
        except Exception as e:
            logger.error(f"处理提案创建事件时发生错误 (帖子ID: {thread_id}): {e}", exc_info=True)

    @commands.Cog.listener(name="on_objection_vote_initiation")
    async def on_objection_vote_initiation(self, dto: ObjectionVotePanelDto):
        """
        监听由 Logic 层在批准后续异议后分派的事件，
        并创建投票收集面板。
        """
        logger.info(f"接收到异议投票启动事件，异议ID: {dto.objection_id}，准备创建UI。")
        # 在事件驱动的流程中，没有 interaction 对象，因此只传递 DTO。
        await self._create_objection_collection_panel(dto)

    @commands.Cog.listener()
    async def on_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议投票结束事件。
        """
        logger.info(
            f"接收到异议投票结束事件，异议ID: {session_dto.objectionId}，分派到 logic 层处理。"
        )
        try:
            # 调用 Logic 层处理数据库事务
            final_result = await self.logic.handle_objection_vote_finished(session_dto, result_dto)

            if not final_result:
                logger.warning(
                    f"处理异议投票结束事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel(final_result)

            # 处理帖子状态变更
            await self._handle_thread_status_after_vote(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_vote_finished 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_objection_collection_expired")
    async def on_objection_collection_expired(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议支持票收集到期事件。
        """
        logger.info(
            f"接收到异议支持票收集到期事件，异议ID: {session_dto.objectionId}，分派到 logic 层处理。"
        )
        try:
            final_result = await self.logic.handle_objection_collection_expired(
                session_dto, result_dto
            )

            if not final_result:
                logger.warning(
                    f"处理异议支持票收集到期事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel_for_collection_expired(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_collection_expired 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_announcement_finished")
    async def on_announcement_finished(self, announcement):
        """
        监听由 Notification cog 分派的公示结束事件。
        """
        logger.info(
            f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}，分派到 logic 层处理。"
        )
        await self.logic.handle_announcement_finished(announcement)

    @commands.Cog.listener()
    async def on_objection_goal_reached(self, result_dto: HandleSupportObjectionResultDto):
        """
        监听异议支持票数达到目标的事件，创建异议帖。
        """
        logger.info(f"异议 {result_dto.objection_id} 已达到目标票数，准备创建异议帖。")

        try:
            # 获取必要的配置和数据
            discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
            if not discussion_channel_id_str:
                raise RuntimeError("未配置提案讨论频道 (discussion)。")

            discussion_channel = await DiscordUtils.fetch_channel(
                self.bot, int(discussion_channel_id_str)
            )
            if not isinstance(discussion_channel, discord.ForumChannel):
                raise RuntimeError("提案讨论频道必须是论坛频道。")

            #  构建帖子内容
            thread_name = f"异议 - {result_dto.proposal_title}"
            content = (
                f"**关联提案**: <#{result_dto.proposal_discussion_thread_id}>\n"
                f"**异议发起人**: <@{result_dto.objector_id}>\n\n"
                f"**理由**:\n{result_dto.objection_reason}\n\n"
                f"现在，请就此异议进行讨论和投票。"
            )

            # 创建异议帖
            thread_with_message = await self.bot.api_scheduler.submit(
                discussion_channel.create_thread(name=thread_name, content=content),
                priority=3,
            )
            objection_thread = thread_with_message[0]
            logger.info(
                f"成功为异议 {result_dto.objection_id} 创建了异议帖: {objection_thread.id}"
            )

            # 更新数据库和原提案
            assert result_dto.objection_id is not None, "Objection ID is required"
            assert result_dto.proposal_discussion_thread_id is not None, (
                "Original proposal thread ID is required"
            )

            await self.logic.handle_objection_thread_creation(
                objection_id=result_dto.objection_id,
                objection_thread_id=objection_thread.id,
                original_proposal_thread_id=result_dto.proposal_discussion_thread_id,
            )

            # 更新原提案帖的标签和标题
            original_thread = await DiscordUtils.fetch_thread(
                self.bot, result_dto.proposal_discussion_thread_id
            )
            if original_thread:
                # 类型守卫，确保父频道是论坛
                if not isinstance(original_thread.parent, discord.ForumChannel):
                    logger.warning(f"帖子 {original_thread.id} 的父频道不是论坛，无法修改标签。")
                    return

                frozen_tag_id = self.bot.config.get("tags", {}).get("frozen")
                if not frozen_tag_id:
                    logger.warning("未在 config.json 中配置 '已冻结' 标签ID")
                    return

                # 准备新标题和新标签
                if not result_dto.proposal_title:
                    logger.warning(f"提案 {result_dto.proposal_id} 缺少标题，无法更新。")
                    return
                clean_title = StringUtils.clean_title(result_dto.proposal_title)
                new_title = f"[冻结中] {clean_title}"

                # 计算新标签
                new_tags = DiscordUtils.calculate_new_tags(
                    current_tags=original_thread.applied_tags,
                    forum_tags=original_thread.parent.available_tags,
                    config=self.bot.config,
                    target_tag_name="frozen",
                )

                # 在原提案帖发送通知
                embed_qo = BuildProposalFrozenEmbedQo(
                    objection_thread_jump_url=objection_thread.jump_url
                )
                notification_embed = ModerationEmbedBuilder.build_proposal_frozen_embed(
                    embed_qo
                )
                await self.bot.api_scheduler.submit(
                    original_thread.send(embed=notification_embed), priority=4
                )

                # 准备编辑参数
                edit_kwargs = {
                    "name": new_title,
                    "archived": True,
                    "locked": True,
                }
                if new_tags is not None:
                    edit_kwargs["applied_tags"] = new_tags

                await self.bot.api_scheduler.submit(
                    original_thread.edit(**edit_kwargs), priority=4
                )
                logger.info(f"已将原提案帖 {original_thread.id} 冻结、关闭并锁定。")

        except (RuntimeError, ValueError) as e:
            logger.error(f"处理 on_objection_goal_reached 事件时出错: {e}")
        except Exception as e:
            logger.error(f"处理 on_objection_goal_reached 事件时发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_edit_objection_reason_submitted")
    async def on_edit_objection_reason_submitted(self, qo: EditObjectionReasonQo):
        """
        监听来自 EditObjectionReasonModal 的事件，处理理由更新的完整流程。
        """
        interaction = qo.interaction
        try:
            # 调用 Logic 层处理业务逻辑和数据库操作
            result_dto = await self.logic.handle_update_objection_reason(qo)

            # 检查操作是否成功
            if not result_dto.success:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(result_dto.message, ephemeral=True), 1
                )
                return

            # 更新审核帖子中的 Embed
            if result_dto.review_thread_id:
                await self._update_review_embed(result_dto)

            # 向用户发送成功反馈
            await self.bot.api_scheduler.submit(
                interaction.followup.send(result_dto.message, ephemeral=True), 1
            )

        except Exception as e:
            logger.error(
                f"处理 on_edit_objection_reason_submitted 事件时发生未知错误: {e}",
                exc_info=True,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("更新理由时发生未知错误。", ephemeral=True), 1
            )

    # --- Private Methods ---

    async def _update_review_embed(self, dto):
        """根据更新后的数据，找到并更新审核帖子中的 embed"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新审核帖子。")
            return

        review_thread = await DiscordUtils.fetch_thread(self.bot, dto.review_thread_id)
        if not review_thread:
            logger.warning(f"无法找到审核帖子 {dto.review_thread_id}，跳过 Embed 更新。")
            return

        try:
            # 假设需要更新的消息是帖子的第一条消息
            history = review_thread.history(limit=1, oldest_first=True)
            original_message = await history.__anext__()

            if not original_message:
                logger.warning(f"审核帖子 {dto.review_thread_id} 中没有消息，无法更新。")
                return

            # 构建新的 Embed
            embed_qo = BuildAdminReviewEmbedQo(
                guild_id=dto.guild_id,
                proposal_id=dto.proposal_id,
                proposal_title=dto.proposal_title,
                proposal_thread_id=dto.proposal_thread_id,
                objection_id=dto.objection_id,
                objector_id=dto.objector_id,
                objection_reason=dto.new_reason,
            )
            new_embed = ModerationEmbedBuilder.build_admin_review_embed(
                embed_qo, self.bot.user
            )

            # 编辑消息
            await self.bot.api_scheduler.submit(
                original_message.edit(embed=new_embed), priority=3
            )
            logger.info(f"成功更新了审核帖子 {dto.review_thread_id} 中的异议理由。")

        except StopAsyncIteration:
            logger.warning(f"审核帖子 {dto.review_thread_id} 为空，无法找到消息进行更新。")
        except Exception as e:
            logger.error(
                f"更新审核帖子 {dto.review_thread_id} 的 Embed 时出错: {e}", exc_info=True
            )

    async def _create_objection_collection_panel(
        self, dto: ObjectionVotePanelDto, interaction: discord.Interaction | None = None
    ):
        """通用方法：根据 DTO 在公示频道创建异议收集面板"""
        # 获取频道
        channel_id_str = self.bot.config.get("channels", {}).get("objection_publicity")
        guild_id_str = self.bot.config.get("guild_id")
        guild = (
            interaction.guild
            if interaction
            else self.bot.get_guild(int(guild_id_str if guild_id_str else 0))
        )

        if not channel_id_str or not guild:
            raise RuntimeError("公示频道或服务器ID未配置，或无法获取服务器信息。")
        channel = await DiscordUtils.fetch_channel(self.bot, int(channel_id_str))

        # 类型守卫，确保公示频道是文本频道
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"异议公示频道 (ID: {channel_id_str}) 必须是一个文本频道。")

        # 构建 Embed 和 View
        objector = await self.bot.fetch_user(dto.objector_id)
        guild_id = guild.id

        proposal_url = f"https://discord.com/channels/{guild_id}/{dto.proposal_thread_id}"

        embed_qo = BuildFirstObjectionEmbedQo(
            proposal_title=dto.proposal_title,
            proposal_url=proposal_url,
            objector_id=dto.objector_id,
            objector_display_name=objector.display_name,
            objection_reason=dto.objection_reason,
            required_votes=dto.required_votes,
        )
        embed = ModerationEmbedBuilder.build_first_objection_embed(embed_qo)

        view = ObjectionCreationVoteView(self.bot)

        # 发送消息
        message = await self.bot.api_scheduler.submit(
            channel.send(embed=embed, view=view), priority=5
        )

        # 更新数据库中的 message_id
        await self.logic.update_vote_session_message_id(
            session_id=dto.vote_session_id, message_id=message.id
        )

    async def _update_publicity_panel(self, result):
        """更新公示频道中的原始投票消息"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新投票面板。")
            return

        channel = (
            await DiscordUtils.fetch_channel(self.bot, result.notification_channel_id)
            if result.notification_channel_id
            else None
        )
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"无法找到ID为 {result.notification_channel_id} 的文本频道。")
            return

        embed = ModerationEmbedBuilder.build_vote_result_embed(result.embed_qo, self.bot.user)

        if result.original_vote_message_id:
            try:
                message = await channel.fetch_message(result.original_vote_message_id)
                await self.bot.api_scheduler.submit(
                    message.edit(embed=embed, view=None), priority=5
                )
            except discord.NotFound:
                logger.warning(
                    f"无法找到原始投票消息 {result.original_vote_message_id}，将发送新消息。"
                )
                await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)
            except Exception as e:
                logger.error(
                    f"更新原始投票消息 {result.original_vote_message_id} 时出错: {e}",
                    exc_info=True,
                )
        else:
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

    async def _update_publicity_panel_for_collection_expired(
        self, result: CollectionExpiredResultDto
    ):
        """更新公示频道中的原始投票消息（收集到期场景）"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新投票面板。")
            return

        channel = (
            await DiscordUtils.fetch_channel(self.bot, result.notification_channel_id)
            if result.notification_channel_id
            else None
        )
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"无法找到ID为 {result.notification_channel_id} 的文本频道。")
            return

        embed = ModerationEmbedBuilder.build_collection_expired_embed(result.embed_qo)

        if result.original_vote_message_id:
            try:
                message = await channel.fetch_message(result.original_vote_message_id)
                await self.bot.api_scheduler.submit(
                    message.edit(embed=embed, view=None), priority=5
                )
            except discord.NotFound:
                logger.warning(
                    f"无法找到原始投票消息 {result.original_vote_message_id}，将发送新消息。"
                )
                await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)
            except Exception as e:
                logger.error(
                    f"更新原始投票消息 {result.original_vote_message_id} 时出错: {e}",
                    exc_info=True,
                )
        else:
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

    async def _handle_thread_status_after_vote(self, result):
        """根据投票结果处理原提案和异议帖的状态"""
        original_thread = await DiscordUtils.fetch_thread(
            self.bot, result.original_proposal_thread_id
        )
        objection_thread = (
            await DiscordUtils.fetch_thread(self.bot, result.objection_thread_id)
            if result.objection_thread_id
            else None
        )

        if not original_thread:
            logger.error(f"找不到原提案帖 {result.original_proposal_thread_id}，无法更新状态。")
            return

        # 类型守卫，确保父频道是论坛
        if not isinstance(original_thread.parent, discord.ForumChannel):
            logger.warning(f"帖子 {original_thread.id} 的父频道不是论坛，无法修改标签。")
            return

        if not self.bot.user:
            logger.error("机器人尚未登录，无法发送结果通知。")
            return

        # 发送所有通知
        await self._send_paginated_vote_results(original_thread, result)
        if objection_thread:
            await self._send_paginated_vote_results(objection_thread, result)

        # 根据投票结果，执行后续的帖子状态变更
        clean_title = StringUtils.clean_title(original_thread.name)

        if result.is_passed:
            # 异议通过 -> 原提案被否决
            new_title = f"[已否决] {clean_title}"
            new_tags = DiscordUtils.calculate_new_tags(
                original_thread.applied_tags,
                original_thread.parent.available_tags,
                self.bot.config,
                "rejected",
            )
            await self.bot.api_scheduler.submit(
                original_thread.edit(
                    name=new_title,
                    applied_tags=new_tags
                    if new_tags is not None
                    else original_thread.applied_tags,
                    archived=True,
                    locked=True,
                ),
                priority=4,
            )
        else:
            # 异议失败 -> 原提案解冻，异议帖被否决

            # 解冻原提案
            if original_thread.archived:
                await self.bot.api_scheduler.submit(
                    original_thread.edit(archived=False), priority=4
                )

            new_title = clean_title
            new_tags = DiscordUtils.calculate_new_tags(
                original_thread.applied_tags,
                original_thread.parent.available_tags,
                self.bot.config,
                "discussion",
            )
            await self.bot.api_scheduler.submit(
                original_thread.edit(
                    name=new_title,
                    applied_tags=new_tags
                    if new_tags is not None
                    else original_thread.applied_tags,
                    locked=False,
                ),
                priority=4,
            )

            # 将异议帖标记为否决并归档
            if objection_thread:
                obj_clean_title = StringUtils.clean_title(objection_thread.name)
                obj_new_title = f"[已否决] {obj_clean_title}"
                rejected_tag_id_str = self.bot.config.get("tags", {}).get("rejected")
                if rejected_tag_id_str:
                    rejected_tag = original_thread.parent.get_tag(
                        int(rejected_tag_id_str)
                    )
                    if rejected_tag:
                        await self.bot.api_scheduler.submit(
                            objection_thread.edit(
                                name=obj_new_title,
                                applied_tags=[rejected_tag],
                                archived=True,
                                locked=True,
                            ),
                            priority=4,
                        )

    async def _send_paginated_vote_results(
        self, channel: discord.TextChannel | discord.Thread, result
    ):
        """根据投票结果，发送主结果面板和分页的投票人列表。"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法发送结果通知。")
            return

        # 发送主结果 Embed
        main_embed = ModerationEmbedBuilder.build_vote_result_embed(
            result.embed_qo, self.bot.user
        )
        await self.bot.api_scheduler.submit(channel.send(embed=main_embed), priority=3)

        # # 准备并发送分页的投票人列表
        # voter_embeds = []
        # if result.approve_voter_ids:
        #     voter_embeds.extend(
        #         ModerationEmbedBuilder.build_voter_list_embeds(
        #             "✅ 赞成方", result.approve_voter_ids, discord.Color.green()
        #         )
        #     )
        # if result.reject_voter_ids:
        #     voter_embeds.extend(
        #         ModerationEmbedBuilder.build_voter_list_embeds(
        #             "❌ 反对方", result.reject_voter_ids, discord.Color.red()
        #         )
        #     )

        # # Discord 一次最多发送 10 个 embeds
        # for i in range(0, len(voter_embeds), 10):
        #     chunk = voter_embeds[i : i + 10]
        #     await self.bot.api_scheduler.submit(channel.send(embeds=chunk), priority=3)

    @commands.Cog.listener("on_objection_creation_vote_cast")
    async def on_objection_creation_vote_cast(
        self, interaction: discord.Interaction, choice: Literal["support", "withdraw"]
    ):
        """
        监听来自 ObjectionCreationVoteView 的投票事件。
        """
        if not interaction.message:
            logger.warning("on_objection_creation_vote_cast 收到一个没有消息的交互。")
            # 可以在这里发送一个临时的错误消息，但通常 view 层已经处理了，所以只记录日志
            return

        logger.info(
            (
                "接收到异议创建投票事件: "
                f"user={interaction.user.id}, choice={choice}, message={interaction.message.id}"
            )
        )

        try:
            # 准备QO并调用Logic层
            qo = ObjectionSupportQo(
                userId=interaction.user.id,
                messageId=interaction.message.id,
                action=choice,
            )

            if choice == "support":
                result_dto = await self.logic.handle_support_objection(qo)
            else:
                result_dto = await self.logic.handle_withdraw_support(qo)

            # 根据返回的DTO更新UI
            original_embed = interaction.message.embeds[0]
            guild_id = self.bot.config.get("guild_id")
            if not guild_id:
                raise RuntimeError("Guild ID 未在 config.json 中配置。")

            if result_dto.is_goal_reached:
                # 目标达成，更新Embed为“完成”状态，并禁用按钮
                new_embed = ObjectionVoteEmbedBuilder.create_goal_reached_embed(
                    original_embed, result_dto, int(guild_id)
                )
                # 创建一个新的、禁用了按钮的视图
                disabled_view = ObjectionCreationVoteView(self.bot)
                for item in disabled_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True

                await self.bot.api_scheduler.submit(
                    interaction.message.edit(embed=new_embed, view=disabled_view), 2
                )
            else:
                # 目标未达成，只更新支持数
                new_embed = ObjectionVoteEmbedBuilder.update_support_embed(
                    original_embed, result_dto, int(guild_id)
                )
                await self.bot.api_scheduler.submit(interaction.message.edit(embed=new_embed), 2)

            # 根据返回的DTO提供精确的用户反馈
            feedback_messages = {
                "supported": "成功支持该异议！",
                "withdrew": "成功撤回支持。",
                "already_supported": "您已经支持过此异议了。",
                "not_supported": "您尚未支持此异议，无法撤回。",
            }
            feedback_message = feedback_messages.get(result_dto.user_action_result, "操作已处理。")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(feedback_message, ephemeral=True), 1
            )

        except (ValueError, RuntimeError) as e:
            logger.warning(f"处理异议创建投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True), 1
            )
        except Exception as e:
            logger.error(f"处理异议创建投票时发生未知错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )
