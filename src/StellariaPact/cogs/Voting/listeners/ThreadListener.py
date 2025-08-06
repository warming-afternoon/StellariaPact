import asyncio
import logging
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils
from StellariaPact.share.TimeUtils import TimeUtils

from ....share.UnitOfWork import UnitOfWork
from ...Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from ..logic.VotingLogic import VotingLogic

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ThreadListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    def cog_load(self):
        self.voting_logic = VotingLogic(self.bot)

    async def _handle_proposal_thread(
        self, thread: discord.Thread, start_message: discord.Message
    ):
        """处理新创建的提案帖"""
        # 分派创建提案的事件
        asyncio.create_task(self._dispatch_proposal_creation(thread, start_message))

        logger.info(f"在新提案帖 '{thread.name}' (ID: {thread.id}) 中创建标准投票面板。")

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                end_time = TimeUtils.parse_discord_timestamp(start_message.content)
                if end_time is None:
                    target_tz = self.bot.config.get("timezone", "UTC")
                    end_time = TimeUtils.get_utc_end_time(duration_hours=48, target_tz=target_tz)

                view = VoteView(self.bot)
                clean_title = StringUtils.clean_title(thread.name)

                embed = VoteEmbedBuilder.create_initial_vote_embed(
                    topic=clean_title,
                    author=None,
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                )
                message = await self.bot.api_scheduler.submit(
                    thread.send(embed=embed, view=view), priority=5
                )

                qo = CreateVoteSessionQo(
                    thread_id=thread.id,
                    context_message_id=message.id,
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                )
                await uow.voting.create_vote_session(qo)
                await uow.commit()
        except Exception as e:
            logger.error(f"无法在提案帖 {thread.id} 中创建投票面板: {e}", exc_info=True)

    async def _handle_objection_thread(
        self, thread: discord.Thread, objection_dto: ObjectionDetailsDto
    ):
        """处理新创建的异议帖"""
        logger.info(f"在新异议帖 '{thread.name}' (ID: {thread.id}) 中创建专用投票面板。")
        # 调用 Voting 模块的逻辑来创建专用的投票面板
        await self.voting_logic.create_objection_vote_panel(thread, objection_dto)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建，并根据帖子类型（提案/异议）进行分流处理。
        """
        discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id_str or thread.parent_id != int(discussion_channel_id_str):
            return

        # 等待以确保数据库记录已写入
        await asyncio.sleep(1)

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                objection_dto = await uow.moderation.get_objection_by_thread_id(thread.id)

            if objection_dto:
                await self._handle_objection_thread(thread, objection_dto)
            else:
                starter_message = await self._get_starter_message(thread)
                if not starter_message:
                    return
                await self._handle_proposal_thread(thread, starter_message)

        except Exception as e:
            logger.error(f"处理帖子创建事件时发生错误 (ID: {thread.id}): {e}", exc_info=True)

    async def _get_starter_message(self, thread: discord.Thread) -> discord.Message | None:
        """安全地获取帖子的启动消息。"""
        try:
            # 尝试从缓存获取
            if thread.starter_message:
                return thread.starter_message
            # 否则，从 API 获取
            return await thread.fetch_message(thread.id)
        except discord.NotFound:
            logger.warning(f"无法找到帖子 {thread.id} 的启动消息，可能已被删除。")
            return None
        except Exception as e:
            logger.error(f"获取帖子 {thread.id} 的启动消息时发生错误: {e}", exc_info=True)
            return None

    async def _dispatch_proposal_creation(
        self, thread: discord.Thread, start_message: discord.Message
    ):
        """从帖子的启动消息中解析出提案人ID，并分派事件"""
        try:
            match = re.search(r"<@(\d+)>", start_message.content)
            if match:
                proposer_id = int(match.group(1))
                title = StringUtils.clean_title(thread.name)
                self.bot.dispatch("proposal_thread_created", thread.id, proposer_id, title)
            else:
                logger.warning(f"在帖子 {thread.id} 的启动消息中未找到提案人ID。")
        except Exception as e:
            logger.error(f"解析提案人 ID 时发生错误 (帖子ID: {thread.id}): {e}", exc_info=True)
