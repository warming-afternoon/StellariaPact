from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.GlobalVotingRestriction import GlobalVotingRestriction


class GlobalVotingRestrictionAlreadyActiveError(ValueError):
    """目标用户已经存在有效的全局投票限制。"""


class GlobalVotingRestrictionNotFoundError(ValueError):
    """目标用户当前没有有效的全局投票限制。"""


class GlobalVotingRestrictionRepository:
    """全局投票资格限制的写入与查询服务。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self, target_user_id: int) -> GlobalVotingRestriction | None:
        statement = select(GlobalVotingRestriction).where(
            GlobalVotingRestriction.target_user_id == target_user_id,
            GlobalVotingRestriction.lifted_at.is_(None),  # type: ignore[union-attr]
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def is_restricted(self, target_user_id: int) -> bool:
        return await self.get_active(target_user_id) is not None

    async def create_restriction(
        self,
        *,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        reason: str,
        evidence_url: str | None = None,
        evidence_filename: str | None = None,
    ) -> GlobalVotingRestriction:
        if await self.get_active(target_user_id):
            raise GlobalVotingRestrictionAlreadyActiveError(
                f"用户 {target_user_id} 已被永久剥夺投票资格。"
            )

        restriction = GlobalVotingRestriction(
            target_user_id=target_user_id,
            moderator_id=moderator_id,
            origin_guild_id=origin_guild_id,
            origin_channel_id=origin_channel_id,
            reason=reason,
            evidence_url=evidence_url,
            evidence_filename=evidence_filename,
        )
        self.session.add(restriction)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise GlobalVotingRestrictionAlreadyActiveError(
                f"用户 {target_user_id} 已被永久剥夺投票资格。"
            ) from exc
        return restriction

    async def lift_restriction(
        self,
        *,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
    ) -> GlobalVotingRestriction:
        restriction = await self.get_active(target_user_id)
        if restriction is None:
            raise GlobalVotingRestrictionNotFoundError(
                f"用户 {target_user_id} 当前没有永久投票资格限制。"
            )

        restriction.lifted_by_id = lifted_by_id
        restriction.lift_reason = lift_reason
        restriction.lifted_at = datetime.now(timezone.utc)
        self.session.add(restriction)
        await self.session.flush()
        return restriction

    async def get_history(self, target_user_id: int) -> list[GlobalVotingRestriction]:
        statement = (
            select(GlobalVotingRestriction)
            .where(GlobalVotingRestriction.target_user_id == target_user_id)
            .order_by(
                GlobalVotingRestriction.created_at.desc(),
                GlobalVotingRestriction.id.desc(),  # type: ignore[union-attr]
            )
        )
        result = await self.session.exec(statement)
        return list(result.all())
