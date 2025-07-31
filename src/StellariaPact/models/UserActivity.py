from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel


class UserActivity(BaseModel, table=True):
    """
    用户投票资格表模型
    """

    # 定义复合唯一约束
    __table_args__ = (
        UniqueConstraint("userId", "contextThreadId", name="unique_user_activity_per_thread"),
    )

    userId: int = Field(description="用户的Discord ID")
    contextThreadId: int = Field(description="上下文的帖子ID")
    messageCount: int = Field(default=0, description="该用户在帖子中的有效发言次数")
    validation: int = Field(default=1, description="用户投票是否有效: 0-无效, 1-有效")
    lastUpdated: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP"),
        },
        description="最后更新时间",
    )
