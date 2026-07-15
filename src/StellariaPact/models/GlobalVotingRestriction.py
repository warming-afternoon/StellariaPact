from datetime import datetime, timezone

from sqlalchemy import Index, text
from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class GlobalVotingRestriction(BaseModel, table=True):
    """机器人实例范围内的永久投票资格限制历史。"""

    __tablename__ = "global_voting_restriction"  # type: ignore
    __table_args__ = (
        Index(
            "ix_global_voting_restriction_user_created",
            "target_user_id",
            "created_at",
        ),
        Index(
            "uq_global_voting_restriction_active_user",
            "target_user_id",
            unique=True,
            sqlite_where=text("lifted_at IS NULL"),
        ),
    )

    target_user_id: int = Field(description="被限制用户的 Discord ID")
    moderator_id: int = Field(index=True, description="执行处罚的管理员 Discord ID")
    origin_guild_id: int = Field(description="执行指令的服务器 Discord ID")
    origin_channel_id: int = Field(description="执行指令的频道 Discord ID")
    reason: str = Field(description="处罚理由")
    evidence_url: str | None = Field(default=None, description="处罚依据图片 URL")
    evidence_filename: str | None = Field(default=None, description="处罚依据图片文件名")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="处罚生效时间",
    )
    lifted_by_id: int | None = Field(default=None, description="执行解除的管理员 Discord ID")
    lift_reason: str | None = Field(default=None, description="解除理由")
    lifted_at: datetime | None = Field(
        default=None,
        sa_type=UTCDateTime,
        description="解除时间；为空表示限制仍有效",
    )
