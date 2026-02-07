from typing import Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models import ProposalIntake
from StellariaPact.share.enums import IntakeStatus


class IntakeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_intake(self, intake: ProposalIntake) -> ProposalIntake:
        self.session.add(intake)
        await self.session.flush()
        await self.session.refresh(intake)
        return intake

    async def get_intake_by_id(
        self, intake_id: int, *, for_update: bool = False
    ) -> Optional[ProposalIntake]:
        statement = select(ProposalIntake).where(ProposalIntake.id == intake_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def update_intake(self, intake: ProposalIntake) -> ProposalIntake:
        """通用的更新方法"""
        self.session.add(intake)
        await self.session.flush()
        await self.session.refresh(intake)
        return intake

    async def get_all_pending_intakes(self) -> Sequence[ProposalIntake]:
        statement = select(ProposalIntake).where(
            ProposalIntake.status == IntakeStatus.PENDING_REVIEW
        )
        result = await self.session.exec(statement)
        return result.all()
