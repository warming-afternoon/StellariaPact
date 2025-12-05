from typing import Optional

from StellariaPact.dto.UserActivityDto import UserActivityDto


class EligibilityService:
    """
    提供用户投票资格判断的服务。
    """

    REQUIRED_MESSAGES = 3

    @staticmethod
    def is_eligible(
        current_activity: Optional[UserActivityDto],
        inherited_activity: Optional[UserActivityDto] = None,
    ) -> bool:
        """
        根据用户活动记录判断其是否有投票资格。
        支持继承父上下文（如提案贴）的发言数。

        Args:
            current_activity: 用户在当前上下文（如异议贴）中的活动记录。
            inherited_activity: 用户在父上下文（如原提案贴）中的活动记录。

        Returns:
            如果用户合格则返回 True，否则返回 False。
        """
        # 计算当前上下文的数值
        current_count = current_activity.message_count if current_activity else 0

        # 如果存在当前记录且被管理员标记无效（如禁言），则直接判负
        if current_activity and not current_activity.validation:
            return False

        # 计算继承上下文的数值
        inherited_count = inherited_activity.message_count if inherited_activity else 0

        # 如果存在继承记录且无效，不应算入有效发言。
        if inherited_activity and not inherited_activity.validation:
            inherited_count = 0

        total_count = current_count + inherited_count

        return total_count >= EligibilityService.REQUIRED_MESSAGES
