from datetime import datetime, timezone

from sqlalchemy import Index, text
from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime
from StellariaPact.share.enums import PunishmentType


class GlobalProposalPunishment(BaseModel, table=True):
    """机器人实例范围内的全局提案处罚历史。"""

    __tablename__ = "global_proposal_punishment"  # type: ignore
    __table_args__ = (
        Index(
            "ix_global_proposal_punishment_user_created",
            "target_user_id",
            "created_at",
        ),
        Index(
            "uq_global_proposal_punishment_active_user_type",
            "target_user_id",
            "punishment_type",
            unique=True,
            sqlite_where=text("lifted_at IS NULL"),
        ),
    )

    target_user_id: int = Field(description="被处罚用户的 Discord ID")
    moderator_id: int = Field(index=True, description="执行处罚的管理员 Discord ID")
    origin_guild_id: int = Field(description="执行指令的服务器 Discord ID")
    origin_channel_id: int = Field(description="执行指令的频道 Discord ID")
    punishment_type: str = Field(
        default=PunishmentType.PERMANENT_VOTING.value,
        description="处罚类型",
    )
    reason: str = Field(description="处罚理由")
    evidence_url: str | None = Field(default=None, description="处罚依据图片 URL")
    evidence_filename: str | None = Field(default=None, description="处罚依据图片文件名")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="处罚生效时间",
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_type=UTCDateTime,
        description="处罚截止时间；为空表示永久",
    )
    lifted_by_id: int | None = Field(default=None, description="执行解除的管理员 Discord ID")
    lift_reason: str | None = Field(default=None, description="解除或覆盖理由")
    lifted_at: datetime | None = Field(
        default=None,
        sa_type=UTCDateTime,
        description="解除或被覆盖时间；为空表示未人工结束",
    )
