import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.Proposal import Proposal
from StellariaPact.share.enums.ProposalStatus import ProposalStatus

logger = logging.getLogger(__name__)


class ProposalService:
    """
    提供处理提案相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_proposal(
        self, thread_id: int, proposer_id: int, title: str, content: str = ""
    ) -> Optional[Proposal]:
        """
        尝试创建一个新的提案，如果因唯一性约束而失败，则静默处理。

        Args:
            thread_id: 提案讨论帖的ID。
            proposer_id: 提案发起人的ID。
            title: 提案的标题。
            content: 提案的内容。

        Returns:
            成功创建则返回 Proposal ORM 对象，如果已存在则返回 None。
        """
        new_proposal = Proposal(
            discussion_thread_id=thread_id,
            proposer_id=proposer_id,
            title=title,
            content=content,
            status=ProposalStatus.DISCUSSION,
        )
        self.session.add(new_proposal)
        try:
            await self.session.flush()
            await self.session.refresh(new_proposal)
            logger.debug(f"成功为帖子 {thread_id} 创建新的提案，发起人: {proposer_id}")
            return new_proposal
        except IntegrityError:
            # 捕获违反唯一约束的错误，意味着提案已存在
            logger.debug(f"提案 (帖子ID: {thread_id}) 已存在，无需重复创建。回滚会话。")
            # 发生错误时，SQLAlchemy 会话会自动回滚，
            # 我们只需确保操作可以安全地继续。
            await self.session.rollback()
            return None

    async def update_proposal_status_by_thread_id(self, thread_id: int, status: int):
        """
        根据帖子ID更新提案的状态。

        Args:
            thread_id: 讨论帖的ID。
            status: 新的状态值。
        """
        statement = (
            update(Proposal)
            .where(Proposal.discussion_thread_id == thread_id)  # type: ignore
            .values(status=status)
            .returning(Proposal.id)  # type: ignore
        )
        result = await self.session.exec(statement)
        updated_id = result.scalar_one_or_none()

        if updated_id is not None:
            logger.debug(
                f"已将帖子 {thread_id} (Proposal ID: {updated_id}) 的提案状态更新为 {status}。"
            )
        else:
            logger.warning(f"尝试更新状态时，未找到帖子 {thread_id} 关联的提案。")

    async def get_proposal_by_thread_id(self, thread_id: int) -> Optional[Proposal]:
        """
        根据帖子ID获取提案 ORM 对象。
        """
        statement = select(Proposal).where(Proposal.discussion_thread_id == thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_proposal_by_id(self, proposal_id: int) -> Optional[Proposal]:
        """
        根据提案ID获取提案 ORM 对象。
        """
        return await self.session.get(Proposal, proposal_id)
