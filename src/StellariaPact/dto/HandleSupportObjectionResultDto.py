from typing import Literal, Optional

from StellariaPact.share.BaseDto import BaseDto


class HandleSupportObjectionResultDto(BaseDto):
    """
    封装了 `objection_support` 服务方法的结果。
    包含了更新UI和进行逻辑判断所需的所有信息。
    """

    # --- 核心状态 ---
    current_supporters: int
    required_supporters: int
    is_goal_reached: bool
    is_vote_recorded: bool  # 用户的本次操作是否被记录为一次有效的投票
    user_action_result: Literal["supported", "withdrew", "already_supported", "not_supported"]
    objection_status: int  # 异议在本次操作发生前的状态

    # --- 用于UI渲染和事件分派的数据 ---
    objection_id: int
    proposal_id: int
    proposal_title: str
    proposal_discussion_thread_id: Optional[int] = None
    objector_id: int
    objection_reason: str
