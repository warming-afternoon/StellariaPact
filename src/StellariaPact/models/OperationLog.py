from datetime import datetime, timezone

from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class OperationLog(BaseModel, table=True):
    """操作记录表"""

    __tablename__ = "operation_log"  # type: ignore

    operator_id: int = Field(index=True, description="操作者 Discord ID")
    """操作者 Discord ID"""

    operator_name: str = Field(description="操作者用户名")
    """操作者用户名"""

    operator_display_name: str = Field(description="操作者服务器显示名称")
    """操作者服务器显示名称"""

    op_type: int = Field(index=True, description="操作类型: 1=提案操作")
    """操作类型: 1=提案操作"""

    action: str = Field(description="操作动作")
    """操作动作, e.g. 'set_special', 'unset_special'"""

    target_type: str = Field(index=True, description="目标类型")
    """目标类型, e.g. 'proposal'"""

    target_id: int = Field(index=True, description="目标 ID")
    """目标 ID"""

    guild_id: int = Field(index=True, description="服务器 ID")
    """服务器 ID"""

    detail: str | None = Field(default=None, description="补充说明")
    """补充说明"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="操作时间",
    )
    """操作时间"""
