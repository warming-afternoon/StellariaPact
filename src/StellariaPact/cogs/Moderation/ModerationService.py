import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserActivity import UserActivity

logger = logging.getLogger(__name__)


class ModerationService:
    """
    提供处理议事管理相关业务逻辑的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_activity(self, user_id: int, thread_id: int) -> Optional[UserActivity]:
        """
        获取用户在特定帖子中的活动记录。

        Args:
            user_id: 用户的Discord ID。
            thread_id: 上下文的帖子ID。

        Returns:
            如果找到则返回 UserActivity 对象，否则返回 None。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == user_id,
            UserActivity.contextThreadId == thread_id,
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def update_user_validation_status(
        self, user_id: int, thread_id: int, is_valid: bool
    ) -> UserActivity:
        """
        更新用户在特定帖子中的投票有效性状态。
        如果记录不存在，则会创建一条新记录。

        Args:
            user_id: 用户的Discord ID。
            thread_id: 上下文的帖子ID。
            is_valid: 用户投票是否有效。

        Returns:
            返回被创建或更新的 UserActivity 对象。
        """
        # 尝试获取现有的活动记录
        user_activity = await self.get_user_activity(user_id, thread_id)

        if user_activity:
            # 如果记录存在，则更新其状态
            user_activity.validation = 1 if is_valid else 0
        else:
            # 如果记录不存在，则创建一条新记录
            user_activity = UserActivity(
                userId=user_id,
                contextThreadId=thread_id,
                validation=1 if is_valid else 0,
            )

        self.session.add(user_activity)
        await self.session.flush()
        return user_activity

    async def create_proposal(self, thread_id: int, proposer_id: int) -> None:
        """
        尝试创建一个新的提案，如果因唯一性约束而失败，则静默处理。

        Args:
            thread_id: 提案讨论帖的ID。
            proposer_id: 提案发起人的ID。
        """
        new_proposal = Proposal(
            discussionThreadId=thread_id, proposerId=proposer_id, status=0
        )
        self.session.add(new_proposal)
        try:
            await self.session.flush()
            logger.debug(f"成功为帖子 {thread_id} 创建新的提案，发起人: {proposer_id}")
        except IntegrityError:
            # 捕获违反唯一约束的错误，意味着提案已存在
            logger.debug(
                f"提案 (帖子ID: {thread_id}) 已存在，无需重复创建。回滚会话。"
            )
            # 发生错误时，SQLAlchemy 会话会自动回滚，
            # 我们只需确保操作可以安全地继续。
            await self.session.rollback()

    async def update_proposal_status_by_thread_id(self, thread_id: int, status: int):
        """
        根据帖子ID更新提案的状态。

        Args:
            thread_id: 讨论帖的ID。
            status: 新的状态值。
        """
        statement = (
            update(Proposal)
            .where(Proposal.discussionThreadId == thread_id)  # type: ignore
            .values(status=status)
            .returning(Proposal.id) # type: ignore
        )
        result = await self.session.exec(statement)
        updated_id = result.scalar_one_or_none()

        if updated_id is not None:
            logger.debug(
                f"已将帖子 {thread_id} (Proposal ID: {updated_id}) 的提案状态更新为 {status}。"
            )
        else:
            logger.warning(f"尝试更新状态时，未找到帖子 {thread_id} 关联的提案。")
