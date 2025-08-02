import logging
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

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
