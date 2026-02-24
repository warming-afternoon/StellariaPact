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

    async def get_intake_by_review_thread_id(self, thread_id: int) -> Optional[ProposalIntake]:
        """
        通过审核帖子 ID 获取 ProposalIntake。

        Args:
            thread_id: 审核帖子的 Discord ID。

        Returns:
            如果找到则返回 ProposalIntake，否则返回 None。
        """
        statement = select(ProposalIntake).where(ProposalIntake.review_thread_id == thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_intake_by_discussion_thread_id(self, thread_id: int) -> Optional[ProposalIntake]:
        """
        通过讨论帖子 ID 获取 ProposalIntake。

        Args:
            thread_id: 讨论帖子的 Discord ID。

        Returns:
            如果找到则返回 ProposalIntake，否则返回 None。
        """
        statement = select(ProposalIntake).where(ProposalIntake.discussion_thread_id == thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_intake_by_voting_message_id(
        self, message_id: int, *, for_update: bool = False
    ) -> Optional[ProposalIntake]:
        """
        通过投票消息 ID 获取 ProposalIntake。

        Args:
            message_id: 投票消息的 Discord ID。
            for_update: 是否使用 FOR UPDATE 锁定行。

        Returns:
            如果找到则返回 ProposalIntake，否则返回 None。
        """
        statement = select(ProposalIntake).where(ProposalIntake.voting_message_id == message_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.exec(statement)
        return result.one_or_none()
