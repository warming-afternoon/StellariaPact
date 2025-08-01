import logging

import discord
from discord.ext import commands, tasks

from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class VoteCloser(commands.Cog):
    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        self.bot = bot
        self.voting_service = voting_service
        self.close_expired_votes.start()

    def cog_unload(self):
        self.close_expired_votes.cancel()

    @tasks.loop(minutes=2)
    async def close_expired_votes(self):
        """
        每2分钟检查一次并关闭已到期的投票。
        """
        logger.info("开始检查已到期的投票...")
        try:
            async with self.bot.db_handler.get_session() as session:
                expired_sessions = await self.voting_service.get_expired_sessions(session)
                for vote_session in expired_sessions:
                    logger.info(f"正在处理已到期的投票会话: {vote_session.id}")
                    result_dto = await self.voting_service.tally_and_close_session(
                        session, vote_session
                    )

                    thread = self.bot.get_channel(vote_session.contextThreadId)
                    if isinstance(thread, discord.Thread):
                        # 构建要@的角色列表
                        roles_to_mention = []
                        role_ids = self.bot.config.get("roles", {})
                        moderator_id = role_ids.get("councilModerator")
                        auditor_id = role_ids.get("executionAuditor")
                        if moderator_id:
                            roles_to_mention.append(f"<@&{moderator_id}>")
                        if auditor_id:
                            roles_to_mention.append(f"<@&{auditor_id}>")

                        mention_string = " ".join(roles_to_mention)

                        # 构建结果Embed
                        embed = discord.Embed(
                            title="投票已结束",
                            description=(
                                f"总票数: {result_dto.totalVotes}\n"
                                f"赞成: {result_dto.approveVotes}\n"
                                f"反对: {result_dto.rejectVotes}"
                            ),
                            color=discord.Color.dark_grey(),
                        )

                        # 发送包含@信息和Embed的消息
                        await self.bot.api_scheduler.submit(
                            thread.send(content=mention_string, embed=embed), priority=5
                        )
        except Exception as e:
            logger.error(f"检查到期投票时发生错误: {e}", exc_info=True)

    @close_expired_votes.before_loop
    async def before_close_expired_votes(self):
        await self.bot.wait_until_ready()
