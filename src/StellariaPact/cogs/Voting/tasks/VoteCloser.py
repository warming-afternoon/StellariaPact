import asyncio
import logging
import random

from discord.ext import commands, tasks

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import VoteSessionDto
from StellariaPact.share import StellariaPactBot, UnitOfWork

logger = logging.getLogger(__name__)


class VoteCloser(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)
        self.close_expired_votes.start()

    def cog_unload(self):
        self.close_expired_votes.cancel()

    @tasks.loop(minutes=1)
    async def close_expired_votes(self):
        """
        每分钟运行一次, 获取并处理已到期且未处理的投票会话
        """
        # logger.debug("开始检查已到期的投票...")
        try:
            # 获取所有过期且未处理的会话
            async with UnitOfWork(self.bot.db_handler) as uow:
                expired_sessions = await uow.vote_session.get_expired_sessions()

            if not expired_sessions:
                # logger.debug("没有发现已到期的投票。")
                return

            for session_dto in expired_sessions:
                await self._process_session(session_dto)

        except Exception as e:
            logger.error(f"获取到期投票列表时发生严重错误: {e}", exc_info=True)

    async def _process_session(self, session_dto: VoteSessionDto):
        """
        处理单个投票会话
        """
        try:
            logger.debug(f"正在处理已到期的投票会话: {session_dto.id}")
            # 计票并关闭
            result_dto = await self.logic.tally_and_close_session(session_dto)

            if result_dto:
                # 根据会话类型和状态分派事件
                await self._dispatch_vote_event(session_dto, result_dto)
        except Exception as e:
            logger.error(f"处理投票会话 {session_dto.id} 时出错: {e}", exc_info=True)

    async def _dispatch_vote_event(self, session_dto: VoteSessionDto, result_dto: VoteDetailDto):
        """
        根据投票会话的类型和状态分派相应的事件
        """
        # 对于提案投票（session_type=1），分派事件 "vote_finished"
        if session_dto.session_type == 1:
            logger.debug(f"提案投票 {session_dto.id} 已结束。分派 'vote_finished' 事件")
            self.bot.dispatch("vote_finished", session_dto, result_dto)

        # 派发更新事件使投票面板（帖子内、频道镜像等）同步其已结束的状态并禁用按钮
        self.bot.dispatch("vote_details_updated", result_dto)

    @close_expired_votes.before_loop
    async def before_close_expired_votes(self):
        await self.bot.wait_until_ready()
        # 增加随机延迟以错开任务启动时间
        await asyncio.sleep(random.randint(0, 30))
