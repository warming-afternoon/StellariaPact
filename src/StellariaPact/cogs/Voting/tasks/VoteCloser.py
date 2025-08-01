import logging

import discord
from discord.ext import commands, tasks

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
                    async with UnitOfWork(self.bot.db_handler) as uow_atomic:
                        result_dto = await uow_atomic.voting.tally_and_close_session(
                            session_dto.id
                        )
                        await uow_atomic.commit()

                    # 步骤 2b: 数据库操作成功后，发送 Discord 通知
                    thread = self.bot.get_channel(session_dto.contextThreadId)
                    if isinstance(thread, discord.Thread):
                        roles_to_mention = []
                        role_ids = self.bot.config.get("roles", {})
                        moderator_id = role_ids.get("councilModerator")
                        auditor_id = role_ids.get("executionAuditor")
                        if moderator_id:
                            roles_to_mention.append(f"<@&{moderator_id}>")
                        if auditor_id:
                            roles_to_mention.append(f"<@&{auditor_id}>")

                        mention_string = " ".join(roles_to_mention)
                        embed = discord.Embed(
                            title="投票已结束",
                            description=(
                                f"总票数: {result_dto.totalVotes}\n"
                                f"赞成: {result_dto.approveVotes}\n"
                                f"反对: {result_dto.rejectVotes}"
                            ),
                            color=discord.Color.dark_grey(),
                        )
                        await self.bot.api_scheduler.submit(
                            thread.send(content=mention_string, embed=embed), priority=5
                        )
                except Exception as e:
                    logger.error(f"处理投票会话 {session_dto.id} 时出错: {e}", exc_info=True)
                    # 单个会话处理失败，记录日志并继续处理下一个

        except Exception as e:
            logger.error(f"获取到期投票列表时发生严重错误: {e}", exc_info=True)

    @close_expired_votes.before_loop
    async def before_close_expired_votes(self):
        await self.bot.wait_until_ready()
