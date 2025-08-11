import asyncio
import logging
import random

from discord.ext import commands, tasks

from StellariaPact.share.enums.ObjectionStatus import ObjectionStatus
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class VoteCloser(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.close_expired_votes.start()

    def cog_unload(self):
        self.close_expired_votes.cancel()

    @tasks.loop(minutes=2)
    async def close_expired_votes(self):
        """
        每2分钟检查一次并关闭已到期的投票。
        """
        logger.info("开始检查已到期的投票...")
        expired_sessions = []
        try:
            # 步骤 1: 在一个只读事务中安全地获取所有过期的会话
            async with UnitOfWork(self.bot.db_handler) as uow:
                expired_sessions = await uow.voting.get_expired_sessions()

            if not expired_sessions:
                logger.info("没有发现已到期的投票。")
                return

            # 步骤 2: 遍历 DTO 列表，为每个会话执行独立的原子操作
            for session_dto in expired_sessions:
                try:
                    logger.info(f"正在处理已到期的投票会话: {session_dto.id}")
                    # 步骤 2a: 在独立的事务中计票和关闭
                    objection_id = None
                    objection_status = None
                    result_dto = None

                    async with UnitOfWork(self.bot.db_handler) as uow_atomic:
                        # 在关闭会话前，先获取其关联的异议状态
                        if session_dto.objectionId:
                            objection = await uow_atomic.moderation.get_objection_by_id(
                                session_dto.objectionId
                            )
                            if objection:
                                objection_id = objection.id
                                objection_status = objection.status

                        result_dto = await uow_atomic.voting.tally_and_close_session(
                            session_dto.id
                        )
                        await uow_atomic.commit()

                    # 步骤 2b: 检查是否为异议投票，并根据异议状态分派不同事件
                    if objection_id and objection_status and result_dto:
                        if objection_status == ObjectionStatus.COLLECTING_VOTES:
                            # 状态为“收集中”的投票过期，意味着支持票收集失败
                            logger.debug(
                                f"异议 {objection_id} 的支持票收集已到期。"
                                "分派 'objection_collection_expired' 事件。"
                            )
                            self.bot.dispatch(
                                "objection_collection_expired", session_dto, result_dto
                            )
                        elif objection_status == ObjectionStatus.VOTING:
                            # 状态为“投票中”的投票过期，是正式的异议投票结束
                            logger.debug(
                                f"异议 {objection_id} 的正式投票已结束。"
                                "分派 'objection_vote_finished' 事件。"
                            )
                            self.bot.dispatch(
                                "objection_vote_finished", session_dto, result_dto
                            )
                        else:
                            logger.warning(
                                f"投票会话 {session_dto.id} 关联的异议 {objection_id} "
                                f"处于意外状态 {objection_status}，不分派事件。"
                            )
                    elif result_dto:
                        # 对于非异议投票，分派一个通用事件
                        logger.debug(
                            f"普通投票 {session_dto.id} 已结束。"
                            "分派 'vote_finished' 事件。"
                        )
                        self.bot.dispatch("vote_finished", session_dto, result_dto)
                except Exception as e:
                    logger.error(f"处理投票会话 {session_dto.id} 时出错: {e}", exc_info=True)
                    # 单个会话处理失败，记录日志并继续处理下一个

        except Exception as e:
            logger.error(f"获取到期投票列表时发生严重错误: {e}", exc_info=True)

    @close_expired_votes.before_loop
    async def before_close_expired_votes(self):
        await self.bot.wait_until_ready()
        # 增加随机延迟以错开任务启动时间
        await asyncio.sleep(random.randint(0, 30))
