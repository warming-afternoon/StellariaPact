import logging
from typing import TYPE_CHECKING

from discord.ext import commands

from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic

if TYPE_CHECKING:
    from StellariaPact.share import StellariaPactBot

logger = logging.getLogger(__name__)


class VotingEventListener(commands.Cog):
    """
    监听来自 Voting 模块的事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)

    @commands.Cog.listener()
    async def on_proposal_under_objection_requested(
        self,
        *,
        thread_id: int,
        trigger_user_id: int | None = None,
        source: str = "unknown",
    ):
        """处理“提案进入异议中”请求。"""
        try:
            await self.logic.mark_proposal_under_objection(thread_id)
            logger.info(
                "已处理“提案进入异议中”请求: "
                f"thread_id={thread_id}, trigger_user_id={trigger_user_id}, source={source}"
            )
        except Exception as e:
            logger.error(
                "处理“提案进入异议中”请求失败: "
                f"thread_id={thread_id}, trigger_user_id={trigger_user_id}, source={source}, error={e}",
                exc_info=True,
            )
