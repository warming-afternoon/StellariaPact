from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models import ProposalIntake
from StellariaPact.share.enums import IntakeStatus


class IntakeRepository:
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
        ).order_by(ProposalIntake.id)  # type: ignore
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

    async def record_approval(
        self,
        thread_id: int,
        reviewer_id: int,
        review_comment: str,
    ) -> tuple[ProposalIntake, int]:
        """原子占用下一个审核位置；仅第三位不同管理能推进状态。"""
        reviewer_columns = [
            ProposalIntake.reviewer_id,
            ProposalIntake.reviewer_id_2,
            ProposalIntake.reviewer_id_3,
        ]
        # UPDATE 先于读取执行，避免 SQLite 的读后写升级竞争。
        for index, suffix in enumerate(("", "_2", "_3")):
            conditions = [
                ProposalIntake.review_thread_id == thread_id,
                ProposalIntake.status == IntakeStatus.PENDING_REVIEW,
                *[column.is_not(None) for column in reviewer_columns[:index]],
                *[column.is_(None) for column in reviewer_columns[index:]],
                *[or_(column.is_(None), column != reviewer_id) for column in reviewer_columns],
            ]
            values = {
                f"reviewer_id{suffix}": reviewer_id,
                f"reviewed_at{suffix}": datetime.now(timezone.utc),
                f"review_comment{suffix}": review_comment,
            }
            if index == 2:
                values["status"] = IntakeStatus.SUPPORT_COLLECTING
            result = await self.session.execute(
                update(ProposalIntake)
                .where(*conditions)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                intake = await self.get_intake_by_review_thread_id(thread_id)
                assert intake is not None
                await self.session.refresh(intake)
                return intake, index + 1

        raise ValueError("无法批准：草案不存在、已不处于待审核状态，或您已审核过此草案。")

    async def mark_reviewed(
        self,
        thread_id: int,
        reviewer_id: int,
        review_comment: str,
        target_status: int,
        *,
        expected_current_status: list[int] | None = None,
    ) -> ProposalIntake:
        """
        根据审核帖子 ID 更新草案审核结果。

        Args:
            thread_id: 审核帖子 Discord ID。
            reviewer_id: 审核员 ID。
            review_comment: 审核意见。
            target_status: 审核完成后要写入的状态。
            expected_current_status: 若提供，则要求当前状态必须匹配。

        Returns:
            更新后的 ProposalIntake。
        """
        intake = await self.get_intake_by_review_thread_id(thread_id)
        if not intake:
            raise ValueError("未找到对应的草案。")

        if expected_current_status is not None:
            if intake.status not in expected_current_status:
                raise ValueError("草案状态不正确，无法更新审核结果。")

        intake.reviewer_id = reviewer_id
        intake.reviewed_at = datetime.now(timezone.utc)
        intake.review_comment = review_comment
        intake.status = target_status

        return await self.update_intake(intake)

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
