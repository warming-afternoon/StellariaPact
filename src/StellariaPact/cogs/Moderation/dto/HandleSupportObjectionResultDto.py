from typing import Optional

from ....share.BaseDto import BaseDto


class HandleSupportObjectionResultDto(BaseDto):
    """
    封装了 `handle_support_objection` 逻辑层方法的结果。
    包含了更新UI和分派事件所需的所有信息。
    """

    votes_count: int
    required_votes: int
    is_goal_reached: bool
    is_vote_recorded: bool  # 指示投票是否成功记录（例如，避免重复投票）

    # --- 用于事件分派的数据 ---
    # 如果 is_goal_reached 为 True，这些字段将被填充
    objection_id: Optional[int] = None
    proposal_id: Optional[int] = None
    proposal_title: Optional[str] = None
    proposal_discussion_thread_id: Optional[int] = None
    objector_id: Optional[int] = None
    objection_reason: Optional[str] = None
