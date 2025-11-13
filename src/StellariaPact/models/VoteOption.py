from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel


class VoteOption(BaseModel, table=True):
    """
    投票会话的选项表
    """

    __tablename__ = "vote_option"  # type: ignore

    __table_args__ = (
        UniqueConstraint("session_id", "choice_index", name="uk_voteoption_session_choice"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, description="关联的投票会话ID")
    choice_index: int = Field(description="选项在此会话中的顺序 (从1开始)")
    choice_text: str = Field(description="选项文本")
