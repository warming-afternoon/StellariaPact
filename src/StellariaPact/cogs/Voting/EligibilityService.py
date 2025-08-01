from typing import Optional

from StellariaPact.cogs.Voting.dto.UserActivityDto import UserActivityDto


class EligibilityService:
    """
    提供用户投票资格判断的服务。
    """

    REQUIRED_MESSAGES = 3

    @staticmethod
    def is_eligible(user_activity: Optional[UserActivityDto]) -> bool:
        """
        根据用户活动记录判断其是否有投票资格。

        Args:
            user_activity: 用户在特定帖子中的活动记录。

        Returns:
            如果用户合格则返回 True，否则返回 False。
        """
        if not user_activity:
            return False

        # 检查发言数和管理员设置的有效性状态
        message_count = user_activity.messageCount
        is_valid_by_admin = user_activity.validation

        return message_count >= EligibilityService.REQUIRED_MESSAGES and is_valid_by_admin
