from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from discord.ext import tasks
from sqlalchemy import select

from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums import IntakeStatus, VoteSessionType
from StellariaPact.share.UnitOfWork import UnitOfWork

if TYPE_CHECKING:
    from .Cog import IntakeCog

logger = logging.getLogger(__name__)


class IntakeCloser:
    """
    Intake 模块清理器：每 5 分钟检查一次已超过 3 天且未达标的草案
    """

    def __init__(self, intake_cog: "IntakeCog"):
        self.intake_cog = intake_cog
        self.bot = intake_cog.bot
        self.check_expired_intakes.start()

    def stop(self):
        self.check_expired_intakes.stop()

    @tasks.loop(minutes=5)
    async def check_expired_intakes(self):
        logger.debug("开始扫描过期草案...")
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 查询：状态为“支持票收集中”且关联的投票会话结束时间早于当前时间的草案
            stmt = (
                select(ProposalIntake.id)  # type: ignore
                .join(VoteSession, VoteSession.intake_id == ProposalIntake.id)
                .where(ProposalIntake.status == IntakeStatus.SUPPORT_COLLECTING)
                .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)
                .where(VoteSession.end_time <= datetime.utcnow())  # type: ignore
            )

            result = await uow.session.execute(stmt)
            expired_ids = result.scalars().all()

            for intake_id in expired_ids:
                try:
                    logger.info(f"草案 {intake_id} 已过期，正在执行关闭处理...")
                    await self.intake_cog.logic.close_expired_intake(uow, intake_id)
                except Exception as e:
                    logger.error(f"关闭过期草案 {intake_id} 时出错: {e}", exc_info=True)

            await uow.commit()

    @check_expired_intakes.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
