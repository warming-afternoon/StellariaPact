import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.dto import ConfirmationSessionDto, ProposalDto
from StellariaPact.share import DiscordUtils
from StellariaPact.share.enums import ProposalStatus

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ModerationListener(commands.Cog):
    """
    监听与议事管理模块相关的内部事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.thread_manager = ProposalThreadManager(bot.config)

    def cog_unload(self):
        pass

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建，如果在提案讨论区，则委托给 ModerationLogic 处理
        """
        # 短暂休眠以等待帖子的启动消息被处理/缓存
        await asyncio.sleep(1)
        # 检查是否在提案讨论区
        discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id_str or thread.parent_id != int(discussion_channel_id_str):
            return

        await self.logic.process_new_discussion_thread(thread)

    @commands.Cog.listener()
    async def on_confirmation_completed(self, session: ConfirmationSessionDto):
        logger.debug(f"接收到确认完成事件，上下文: {session.context}，目标ID: {session.target_id}")

        try:
            proposal_dto: ProposalDto | None = None
            target_status: ProposalStatus | None = None

            target_status_map = {
                "proposal_execution": ProposalStatus.EXECUTING,
                "proposal_completion": ProposalStatus.FINISHED,
                "proposal_abandonment": ProposalStatus.ABANDONED,
                "proposal_rediscuss": ProposalStatus.DISCUSSION,
            }
            target_status = target_status_map.get(session.context)

            if target_status is None:
                logger.warning(f"未知的确认上下文: {session.context}")
                return

            proposal_dto = await self.logic.proposal_status_change(
                session.target_id, target_status
            )

            if proposal_dto and target_status is not None and proposal_dto.discussion_thread_id:
                await self._update_thread_status_after_confirmation(
                    proposal_dto.discussion_thread_id,
                    proposal_dto.title,
                    target_status,
                )
            else:
                logger.warning(
                    "从 logic 层返回的 proposal_dto 为空，无法更新帖子状态。"
                    f"Proposal ID: {session.target_id}"
                )

        except Exception as e:
            logger.error(f"处理确认完成事件时出错: {e}", exc_info=True)

    async def _update_thread_status_after_confirmation(
        self, thread_id: int, title: str, target_status: ProposalStatus
    ):
        """根据确认结果更新帖子状态"""
        try:
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if not thread:
                logger.warning(f"无法找到ID为 {thread_id} 的帖子，无法更新状态。")
                return

            # 将枚举映射到状态关键字
            status_key_map = {
                ProposalStatus.EXECUTING: "executing",
                ProposalStatus.FINISHED: "finished",
                ProposalStatus.ABANDONED: "abandoned",
                ProposalStatus.DISCUSSION: "discussion",
                ProposalStatus.UNDER_OBJECTION: "under_objection",
            }
            status_key = status_key_map.get(target_status)

            if status_key:
                await self.thread_manager.update_status(thread, status_key)
            else:
                logger.warning(f"未知的提案状态: {target_status}，无法更新帖子。")

        except Exception as e:
            logger.error(f"更新帖子 {thread_id} 状态时发生未知错误: {e}", exc_info=True)
