import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ....cogs.Moderation.dto.CollectionExpiredResultDto import CollectionExpiredResultDto
from ....cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from ....cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from ....dto.VoteSessionDto import VoteSessionDto
from ....share.DiscordUtils import DiscordUtils
from ..ModerationLogic import ModerationLogic
from ..thread_manager import ProposalThreadManager

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class VotingEventListener(commands.Cog):
    """
    监听来自 Voting 模块的事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.thread_manager = ProposalThreadManager(bot.config)

    @commands.Cog.listener()
    async def on_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议投票结束事件
        """
        logger.info(
            f"接收到异议投票结束事件，异议ID: {session_dto.objection_id}，分派到 logic 层处理。"
        )
        try:
            # 调用 Logic 层处理数据库事务
            final_result = await self.logic.handle_objection_vote_finished(session_dto, result_dto)

            if not final_result:
                logger.warning(
                    f"处理异议投票结束事件 (异议ID: {session_dto.objection_id}) 未返回有效结果。"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel(final_result)

            # 处理帖子状态变更
            await self._handle_thread_status_after_vote(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_vote_finished 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_objection_collection_expired(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议支持票收集到期事件。
        """
        logger.info(
            f"接收到异议支持票收集到期事件，异议ID: {session_dto.objection_id}，"
            "分派到 logic 层处理"
        )
        try:
            final_result = await self.logic.handle_objection_collection_expired(
                session_dto, result_dto
            )

            if not final_result:
                logger.warning(
                    f"处理异议支持票收集到期事件 (ID: {session_dto.objection_id}) 未返回有效结果"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel_for_collection_expired(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_collection_expired 中发生意外错误: {e}", exc_info=True)

    # --- 私有方法 ---

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
        if result.is_passed:
            # 异议通过 -> 原提案被否决
            if original_thread:
                await self.thread_manager.update_status(original_thread, "rejected")
        else:
            # 异议失败 -> 原提案解冻
            if original_thread:
                await self.thread_manager.update_status(original_thread, "discussion")
            # 将异议帖标记为否决并归档
            if objection_thread:
                await self.thread_manager.update_status(objection_thread, "rejected")

    async def _send_paginated_vote_results(
        self, channel: discord.TextChannel | discord.Thread, result
    ):
        """根据投票结果，发送主结果面板和分页的投票人列表"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法发送结果通知。")
            return

        # 发送主结果 Embed
        main_embed = ModerationEmbedBuilder.build_vote_result_embed(result.embed_qo, self.bot.user)
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
        #
        # # Discord 一次最多发送 10 个 embeds
        # for i in range(0, len(voter_embeds), 10):
        #     chunk = voter_embeds[i : i + 10]
        #     await self.bot.api_scheduler.submit(channel.send(embeds=chunk), priority=3)
