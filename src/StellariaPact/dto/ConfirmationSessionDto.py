from typing import Dict, List, Optional

from pydantic import Field

from StellariaPact.share.BaseDto import BaseDto


class ConfirmationSessionDto(BaseDto):
    """
    ConfirmationSession 的数据传输对象
    """

    id: int = Field(description="确认会话的唯一标识符。")
    context: str = Field(
        description="会话的上下文，例如 'proposal_execution' 或 'proposal_completion'。"
    )
    status: int = Field(description="会话状态 (0-待处理, 1-已完成, 2-已取消)。")
    canceler_id: Optional[int] = Field(
        default=None, description="取消该会话的用户ID（如果已取消）。"
    )
    confirmed_parties: Dict[str, int] = Field(description="已确认的角色及其对应的用户ID映射。")
    required_roles: List[str] = Field(description="需要进行确认的角色列表。")
    target_id: int = Field(description="关联的业务对象ID（例如 Proposal.id）。")
    message_id: Optional[int] = Field(default=None, description="机器人发送的确认消息ID。")
