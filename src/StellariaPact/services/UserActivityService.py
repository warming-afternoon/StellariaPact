import logging
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import UpdateUserActivityQo
from StellariaPact.models.UserActivity import UserActivity

logger = logging.getLogger(__name__)


class UserActivityService:
    """
    提供处理用户活动表 (`UserActivity`) 相关数据库操作
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_activity(self, user_id: int, thread_id: int) -> UserActivity | None:
        """
        获取用户在特定帖子中的活动记录。
        """
        statement = select(UserActivity).where(
            UserActivity.user_id == user_id,
            UserActivity.context_thread_id == thread_id,
        )
        result = await self.session.exec(statement)
        activity = result.one_or_none()
        return activity

    async def update_user_activity(self, qo: UpdateUserActivityQo) -> UserActivity:
        """
        更新用户在特定帖子中的有效发言计数。
        如果用户活动记录不存在，则会创建一个。
        """
        statement = select(UserActivity).where(
            UserActivity.user_id == qo.user_id,
            UserActivity.context_thread_id == qo.thread_id,
        )
        result = await self.session.exec(statement)
        user_activity = result.one_or_none()

        if user_activity:
            # 确保计数不会变为负数
            new_count = user_activity.message_count + qo.change
            user_activity.message_count = max(0, new_count)
        else:
            # 如果是减少操作，但记录不存在，则无需创建
            if qo.change < 0:
                # 返回一个临时的、未保存的实例，表示没有变化
                return UserActivity(
                    id=-1,  # Placeholder ID
                    user_id=qo.user_id,
                    context_thread_id=qo.thread_id,
                    message_count=0,
                    validation=True,
                )
            # 仅在增加时创建新记录
            user_activity = UserActivity(
                user_id=qo.user_id,
                context_thread_id=qo.thread_id,
                message_count=1,
            )

        self.session.add(user_activity)
        await self.session.flush()
        return user_activity

    async def update_user_validation_status(
        self,
        user_id: int,
        thread_id: int,
        is_valid: bool,
        mute_end_time: datetime | None = None,
    ) -> UserActivity:
        """
        更新用户在特定帖子中的投票有效性和禁言状态。
        如果记录不存在，则会创建一条新记录。

        Args:
            user_id: 用户的Discord ID。
            thread_id: 上下文的帖子ID。
            is_valid: 用户投票是否有效。
            mute_end_time: 禁言截止时间

        Returns:
            返回被创建或更新的 UserActivity 对象。
        """
        # 尝试获取现有的活动记录
        user_activity = await self.get_user_activity(user_id, thread_id)

        if user_activity:
            # 如果记录存在，则更新其状态
            user_activity.validation = 1 if is_valid else 0
            user_activity.mute_end_time = mute_end_time
        else:
            # 如果记录不存在，则创建一条新记录
            user_activity = UserActivity(
                user_id=user_id,
                context_thread_id=thread_id,
                validation=1 if is_valid else 0,
                mute_end_time=mute_end_time,
            )

        self.session.add(user_activity)
        await self.session.flush()
        return user_activity
