from typing import Literal, Optional

from StellariaPact.share.BaseDto import BaseDto


class HandleSupportObjectionResultDto(BaseDto):
    """
    封装了 `objection_support` 服务方法的结果。
    包含了更新UI和进行逻辑判断所需的所有信息。
    """

    # --- 核心状态 ---
    current_supporters: int
    """当前支持者数量"""

    required_supporters: int
    """所需支持者数量"""

    is_goal_reached: bool
    """是否达到目标"""

    is_vote_recorded: bool
    """用户的本次操作是否被记录为一次有效的投票"""

    user_action_result: Literal["supported", "withdrew", "already_supported", "not_supported"]
    """用户操作结果: <br>
    supported-支持, withdrew-撤回, already_supported-已支持, not_supported-未支持"""

    objection_status: int
    """异议在本次操作发生前的状态"""

    # --- 用于UI渲染和事件分派的数据 ---
    objection_id: int
    """异议ID"""

    proposal_id: int
    """提案ID"""

    proposal_title: str
    """提案标题"""

    proposal_discussion_thread_id: Optional[int] = None
    """提案讨论帖ID"""

    objector_id: int
    """异议发起人的Discord ID"""

    objection_reason: str
    """反对理由"""
