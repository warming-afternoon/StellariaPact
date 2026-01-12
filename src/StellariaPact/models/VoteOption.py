from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint, text
from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel


class VoteOption(BaseModel, table=True):
    """
    投票会话的选项表
    """

    __tablename__ = "vote_option"  # type: ignore

    # 唯一约束：会话ID + 选项类型 + 排序索引 必须唯一
    __table_args__ = (
        UniqueConstraint("session_id", "option_type", "choice_index", name="uk_vote_option_session_type_choice"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    """主键ID"""

    session_id: int = Field(index=True, description="关联的投票会话ID")
    """关联的投票会话ID"""

    option_type: int = Field(default=0, description="选项类型: 0-普通提案选项, 1-异议选项")
    """选项类型: 0-普通提案选项, 1-异议选项"""

    choice_index: int = Field(description="该选项在此会话、此类型中的排序 (从1开始)")
    """该选项在此会话、此类型中的排序 (从1开始)"""

    choice_text: str = Field(description="选项文本")
    """选项文本"""

    creator_id: Optional[int] = Field(default=None, description="选项创建人的 Discord ID")
    """选项创建人的 Discord ID"""

    creator_name: Optional[str] = Field(default=None, description="选项创建人的 Discord 昵称")
    """选项创建人的 Discord 昵称"""

    data_status: int = Field(default=1, index=True, description="数据状态: 0-已删除, 1-正常")
    """数据状态: 0-已删除, 1-正常"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    """创建时间"""
