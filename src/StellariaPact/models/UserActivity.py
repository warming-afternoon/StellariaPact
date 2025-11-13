from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr
from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel


class UserActivity(BaseModel, table=True):
    """
    用户投票资格表模型
    """

    __tablename__ = "user_activity"  # type: ignore

    user_id: int = Field(index=True, description="用户的Discord ID")
    context_thread_id: int = Field(index=True, description="上下文的帖子ID")
    message_count: int = Field(default=0, description="该用户在帖子中的有效发言次数")
    validation: int = Field(default=1, description="用户投票是否有效: 0-无效, 1-有效")
    mute_end_time: Optional[datetime] = Field(default=None, description="禁言截止的UTC时间")
    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP"),
        },
        description="最后更新时间",
    )

    @declared_attr  # type: ignore
    def __table_args__(cls):
        return (
            UniqueConstraint(
                cls.user_id,  # type: ignore
                cls.context_thread_id,  # type: ignore
                name="uk_user_activity_per_thread",
            ),
        )
