from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.GlobalProposalPunishment import GlobalProposalPunishment
from StellariaPact.share.enums import PunishmentType

from .GlobalProposalPunishmentAlreadyActiveError import (
    GlobalProposalPunishmentAlreadyActiveError,
)
from .GlobalProposalPunishmentNotFoundError import GlobalProposalPunishmentNotFoundError


class GlobalProposalPunishmentRepository:
    """全局提案处罚的写入与查询服务。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(
        self,
        target_user_id: int,
        punishment_type: PunishmentType | str,
        *,
        now: datetime | None = None,
    ) -> GlobalProposalPunishment | None:
        current_time = now or datetime.now(timezone.utc)
        statement = select(GlobalProposalPunishment).where(
            GlobalProposalPunishment.target_user_id == target_user_id,
            GlobalProposalPunishment.punishment_type == str(punishment_type),
            GlobalProposalPunishment.lifted_at.is_(None),  # type: ignore[union-attr]
            or_(
                GlobalProposalPunishment.expires_at.is_(None),  # type: ignore[union-attr]
                GlobalProposalPunishment.expires_at > current_time,
            ),
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_unresolved(
        self,
        target_user_id: int,
        punishment_type: PunishmentType | str,
    ) -> GlobalProposalPunishment | None:
        statement = select(GlobalProposalPunishment).where(
            GlobalProposalPunishment.target_user_id == target_user_id,
            GlobalProposalPunishment.punishment_type == str(punishment_type),
            GlobalProposalPunishment.lifted_at.is_(None),  # type: ignore[union-attr]
        )
        return (await self.session.exec(statement)).one_or_none()

    async def is_restricted(
        self,
        target_user_id: int,
        punishment_types: Iterable[PunishmentType | str] | PunishmentType | str | None = None,
    ) -> bool:
        if punishment_types is None:
            types = (
                PunishmentType.PERMANENT_VOTING,
                PunishmentType.PROPOSAL_VIOLATION,
            )
        elif isinstance(punishment_types, str):
            types = (punishment_types,)
        else:
            types = tuple(punishment_types)
        for punishment_type in types:
            if await self.get_active(target_user_id, punishment_type):
                return True
        return False

    async def is_proposal_violation_restricted(self, target_user_id: int) -> bool:
        return await self.get_active(
            target_user_id, PunishmentType.PROPOSAL_VIOLATION
        ) is not None

    async def create_punishment(
        self,
        *,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        punishment_type: PunishmentType | str,
        reason: str,
        expires_at: datetime | None = None,
        evidence_url: str | None = None,
        evidence_filename: str | None = None,
        replace_existing: bool = False,
    ) -> GlobalProposalPunishment:
        type_value = str(punishment_type)
        unresolved = await self.get_unresolved(target_user_id, type_value)
        if unresolved is not None:
            if not replace_existing:
                raise GlobalProposalPunishmentAlreadyActiveError(
                    f"用户 {target_user_id} 已存在有效的同类型处罚。"
                )
            now = datetime.now(timezone.utc)
            unresolved.lifted_by_id = moderator_id
            unresolved.lift_reason = "被新的同类型处罚覆盖"
            unresolved.lifted_at = now
            self.session.add(unresolved)
            await self.session.flush()

        punishment = GlobalProposalPunishment(
            target_user_id=target_user_id,
            moderator_id=moderator_id,
            origin_guild_id=origin_guild_id,
            origin_channel_id=origin_channel_id,
            punishment_type=type_value,
            reason=reason,
            expires_at=expires_at,
            evidence_url=evidence_url,
            evidence_filename=evidence_filename,
        )
        self.session.add(punishment)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise GlobalProposalPunishmentAlreadyActiveError(
                f"用户 {target_user_id} 已存在有效的同类型处罚。"
            ) from exc
        return punishment

    async def lift_punishment(
        self,
        *,
        target_user_id: int,
        punishment_type: PunishmentType | str,
        lifted_by_id: int,
        lift_reason: str,
    ) -> GlobalProposalPunishment:
        punishment = await self.get_active(target_user_id, punishment_type)
        if punishment is None:
            raise GlobalProposalPunishmentNotFoundError(
                f"用户 {target_user_id} 当前没有有效的指定类型处罚。"
            )
        punishment.lifted_by_id = lifted_by_id
        punishment.lift_reason = lift_reason
        punishment.lifted_at = datetime.now(timezone.utc)
        self.session.add(punishment)
        await self.session.flush()
        return punishment

    async def get_active_by_type(
        self,
        punishment_type: PunishmentType | str,
        *,
        now: datetime | None = None,
    ) -> list[GlobalProposalPunishment]:
        current_time = now or datetime.now(timezone.utc)
        statement = select(GlobalProposalPunishment).where(
            GlobalProposalPunishment.punishment_type == str(punishment_type),
            GlobalProposalPunishment.lifted_at.is_(None),  # type: ignore[union-attr]
            or_(
                GlobalProposalPunishment.expires_at.is_(None),  # type: ignore[union-attr]
                GlobalProposalPunishment.expires_at > current_time,
            ),
        )
        return list((await self.session.exec(statement)).all())

    async def get_history(self, target_user_id: int) -> list[GlobalProposalPunishment]:
        statement = (
            select(GlobalProposalPunishment)
            .where(GlobalProposalPunishment.target_user_id == target_user_id)
            .order_by(
                GlobalProposalPunishment.created_at.desc(),
                GlobalProposalPunishment.id.desc(),  # type: ignore[union-attr]
            )
        )
        return list((await self.session.exec(statement)).all())
