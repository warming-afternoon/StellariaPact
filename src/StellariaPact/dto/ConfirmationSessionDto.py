from datetime import datetime
from typing import Dict, List, Optional

from pydantic import Field

from StellariaPact.share.BaseDto import BaseDto


class ConfirmationSessionDto(BaseDto):
    """
    ConfirmationSession 的数据传输对象
    """

    id: int = Field(description="确认会话的唯一标识符")
    """主键ID"""

    context: str = Field(
        description="会话的上下文，例如 'proposal_execution' 或 'proposal_completion'"
    )
    """确认会话的上下文，如 'proposal_execution'"""

    status: int = Field(description="会话状态 (0-待处理, 1-已完成, 2-已取消)。")
    """会话状态: 0-待处理, 1-已完成, 2-已取消"""

    canceler_id: Optional[int] = Field(
        default=None, description="取消该会话的用户ID（如果已取消）"
    )
    """取消该会话的用户ID"""

    confirmed_parties: Dict[str, int] = Field(description="已确认的角色及其对应的用户ID映射")
    """已确认的角色及用户ID"""

    required_roles: List[str] = Field(description="需要进行确认的角色列表。")
    """需要进行确认的角色列表"""

    target_id: int = Field(description="关联的业务对象ID（例如 Proposal.id）")
    """关联的业务对象ID，如 Proposal.id"""

    message_id: Optional[int] = Field(default=None, description="机器人发送的确认消息ID")
    """机器人发送的确认消息ID"""

    reason: Optional[str] = Field(default=None, description="执行此操作的原因")
    """执行此操作的原因"""

    created_at: datetime = Field(description="创建时间")
    """创建时间"""

    updated_at: datetime = Field(description="最后更新时间")
    """最后更新时间"""
