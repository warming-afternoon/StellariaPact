import logging
from datetime import datetime, timedelta

import discord

from ...Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..qo.CreateVoteSessionQo import CreateVoteSessionQo
from ..views.ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder
from ..views.ObjectionVoteView import ObjectionVoteView

logger = logging.getLogger(__name__)


class VotingLogic:
    """
    处理与投票相关的复杂业务逻辑。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def create_objection_vote_panel(
        self, thread: discord.Thread, objection_dto: ObjectionDetailsDto
    ):
        """
        在异议帖中创建专用的裁决投票面板。
        """
        # 1. 构建 UI
        view = ObjectionVoteView(self.bot)
        embed = ObjectionVoteEmbedBuilder.create_embed(objection_dto=objection_dto)

        # 2. 发送消息
        message = await self.bot.api_scheduler.submit(
            thread.send(embed=embed, view=view), priority=2
        )

        # 3. 在数据库中创建会话
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 默认投票时长为 48 小时
            end_time = datetime.utcnow() + timedelta(hours=48)
            qo = CreateVoteSessionQo(
                thread_id=thread.id,
                objection_id=objection_dto.objection_id,
                context_message_id=message.id,
                realtime=False,
                anonymous=True,
                end_time=end_time,
            )
            await uow.voting.create_vote_session(qo)

        logger.info(
            f"已在异议帖 {thread.id} 中为异议 {objection_dto.objection_id} 创建了投票面板。"
        )
