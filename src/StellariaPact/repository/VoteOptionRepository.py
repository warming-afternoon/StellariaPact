from datetime import datetime, timezone
from typing import List, Optional, Sequence

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.dto import ObjectionViolationRecordDto
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums import ObjectionResolutionType, VoteOptionStatus


class VoteOptionRepository:
    """
    提供处理投票选项 (`VoteOption`) 相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_vote_options(
        self,
        session_id: int,
        options: List[str],
        option_type: int = 0,
        creator_id: Optional[int] = None,
        creator_name: Optional[str] = None
    ):
        """为指定的会话创建投票选项"""
        for i, text in enumerate(options):
            new_option = VoteOption(
                session_id=session_id,
                option_type=option_type,
                choice_index=i + 1,
                choice_text=text,
                creator_id=creator_id,
                creator_name=creator_name,
                data_status=1,
                voting_status=VoteOptionStatus.ACTIVE,
            )
            self.session.add(new_option)
        await self.session.flush()

    async def add_option(
        self,
        session_id: int,
        option_type: int,
        text: str,
        creator_id: Optional[int] = None,
        creator_name: Optional[str] = None
    ) -> VoteOption:
        """动态添加一个新选项，并自动计算该类型下的最新 choice_index"""
        statement = select(func.max(VoteOption.choice_index)).where(
            VoteOption.session_id == session_id,
            VoteOption.option_type == option_type
        )
        max_index = (await self.session.exec(statement)).one_or_none() or 0

        new_option = VoteOption(
            session_id=session_id,
            option_type=option_type,
            choice_index=max_index + 1,
            choice_text=text,
            creator_id=creator_id,
            creator_name=creator_name,
            data_status=1,
            voting_status=VoteOptionStatus.ACTIVE,
        )
        self.session.add(new_option)
        await self.session.flush()
        return new_option

    async def get_vote_options(self, session_id: int) -> Sequence[VoteOption]:
        """获取指定会话的所有投票选项（仅限正常状态）"""
        statement = (
            select(VoteOption)
            .where(
                VoteOption.session_id == session_id,
                VoteOption.data_status == 1  # 过滤逻辑删除
            )
            .order_by(VoteOption.option_type, VoteOption.choice_index)  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_options_by_type(self, session_id: int, option_type: int) -> Sequence[VoteOption]:
        """获取指定类型且未删除的投票选项"""
        statement = select(VoteOption).where(
            VoteOption.session_id == session_id,
            VoteOption.option_type == option_type,
            VoteOption.data_status == 1  # 过滤逻辑删除
        ).order_by(VoteOption.choice_index) # type: ignore
        return (await self.session.exec(statement)).all()

    async def get_active_options_by_type(
        self, session_id: int, option_type: int
    ) -> Sequence[VoteOption]:
        """获取指定类型且仍可投票的选项。"""
        statement = (
            select(VoteOption)
            .where(
                VoteOption.session_id == session_id,
                VoteOption.option_type == option_type,
                VoteOption.data_status == 1,
                VoteOption.voting_status == VoteOptionStatus.ACTIVE,
            )
            .order_by(VoteOption.choice_index)  # type: ignore
        )
        return (await self.session.exec(statement)).all()

    async def get_active_option(
        self, session_id: int, option_type: int, choice_index: int
    ) -> Optional[VoteOption]:
        """按会话、类型和索引获取进行中的选项。"""
        statement = select(VoteOption).where(
            VoteOption.session_id == session_id,
            VoteOption.option_type == option_type,
            VoteOption.choice_index == choice_index,
            VoteOption.data_status == 1,
            VoteOption.voting_status == VoteOptionStatus.ACTIVE,
        )
        return (await self.session.exec(statement)).one_or_none()

    async def get_option_by_id(self, option_id: int) -> Optional[VoteOption]:
        """获取未被逻辑删除的选项。"""
        statement = select(VoteOption).where(
            VoteOption.id == option_id,
            VoteOption.data_status == 1,
        )
        return (await self.session.exec(statement)).one_or_none()

    async def get_options_by_session_ids(
        self, session_ids: list[int], option_type: int
    ) -> Sequence[VoteOption]:
        """批量获取多个会话下（未被逻辑删除）的特定类型选项"""
        if not session_ids:
            return []

        statement = (
            select(VoteOption)
            .where(
                VoteOption.session_id.in_(session_ids),  # type: ignore
                VoteOption.option_type == option_type,
                VoteOption.data_status == 1,
            )
            .order_by(VoteOption.session_id, VoteOption.choice_index)  # type: ignore
        )
        return (await self.session.exec(statement)).all()

    async def get_active_options_by_session_ids(
        self, session_ids: list[int], option_type: int
    ) -> Sequence[VoteOption]:
        """批量获取多个会话下进行中的特定类型选项。"""
        if not session_ids:
            return []

        statement = (
            select(VoteOption)
            .where(
                VoteOption.session_id.in_(session_ids),  # type: ignore
                VoteOption.option_type == option_type,
                VoteOption.data_status == 1,
                VoteOption.voting_status == VoteOptionStatus.ACTIVE,
            )
            .order_by(VoteOption.session_id, VoteOption.choice_index)  # type: ignore
        )
        return (await self.session.exec(statement)).all()

    async def get_latest_active_objections_in_thread(
        self, thread_id: int, limit: int = 25
    ) -> Sequence[VoteOption]:
        """获取帖子中最新的进行中异议。"""
        statement = (
            select(VoteOption)
            .join(VoteSession, VoteSession.id == VoteOption.session_id)  # type: ignore[arg-type]
            .where(
                VoteSession.context_thread_id == thread_id,
                VoteOption.option_type == 1,
                VoteOption.data_status == 1,
                VoteOption.voting_status == VoteOptionStatus.ACTIVE,
            )
            .order_by(VoteOption.created_at.desc(), VoteOption.id.desc())  # type: ignore
            .limit(limit)
        )
        return (await self.session.exec(statement)).all()

    async def get_active_objections_by_ids_in_thread(
        self, thread_id: int, option_ids: list[int]
    ) -> Sequence[VoteOption]:
        """按 ID 获取属于指定帖子的进行中异议。"""
        if not option_ids:
            return []
        statement = (
            select(VoteOption)
            .join(VoteSession, VoteSession.id == VoteOption.session_id)  # type: ignore[arg-type]
            .where(
                VoteSession.context_thread_id == thread_id,
                VoteOption.id.in_(option_ids),  # type: ignore[union-attr]
                VoteOption.option_type == 1,
                VoteOption.data_status == 1,
                VoteOption.voting_status == VoteOptionStatus.ACTIVE,
            )
            .order_by(VoteOption.created_at.desc(), VoteOption.id.desc())  # type: ignore
        )
        return (await self.session.exec(statement)).all()

    async def close_active_options(
        self,
        session_ids: list[int],
        option_type: int,
        resolution_type: int = ObjectionResolutionType.NORMAL,
        resolution_description: str | None = None,
    ) -> Sequence[VoteOption]:
        """结束指定会话中所有进行中的特定类型选项。"""
        options = await self.get_active_options_by_session_ids(session_ids, option_type)
        return await self._close_options(
            options,
            resolution_type=resolution_type,
            resolution_description=resolution_description,
        )

    async def close_active_objections_by_ids(
        self,
        session_ids: list[int],
        option_ids: list[int],
        resolution_type: int,
        resolution_description: str | None,
    ) -> Sequence[VoteOption]:
        """关闭仍在进行中的指定异议；已关闭记录不会被覆盖。"""
        if not session_ids or not option_ids:
            return []
        statement = (
            select(VoteOption)
            .where(
                VoteOption.session_id.in_(session_ids),  # type: ignore[union-attr]
                VoteOption.id.in_(option_ids),  # type: ignore[union-attr]
                VoteOption.option_type == 1,
                VoteOption.data_status == 1,
                VoteOption.voting_status == VoteOptionStatus.ACTIVE,
            )
            .order_by(VoteOption.session_id, VoteOption.choice_index)  # type: ignore
        )
        options = (await self.session.exec(statement)).all()
        return await self._close_options(
            options,
            resolution_type=resolution_type,
            resolution_description=resolution_description,
        )

    async def _close_options(
        self,
        options: Sequence[VoteOption],
        *,
        resolution_type: int,
        resolution_description: str | None,
    ) -> Sequence[VoteOption]:
        """写入关闭状态和处理分类。"""
        closed_at = datetime.now(timezone.utc)
        for option in options:
            option.voting_status = VoteOptionStatus.CLOSED
            option.closed_at = closed_at
            option.resolution_type = resolution_type
            option.resolution_description = resolution_description
            self.session.add(option)
        if options:
            await self.session.flush()
        return options

    async def get_malicious_objection_summary(
        self,
        *,
        guild_id: int,
        creator_id: int,
        limit: int = 4,
    ) -> tuple[int, list[ObjectionViolationRecordDto]]:
        """查询服务器内某用户被认定为恶意违规的异议。"""
        filters = (
            VoteSession.guild_id == guild_id,
            VoteOption.creator_id == creator_id,
            VoteOption.option_type == 1,
            VoteOption.data_status == 1,
            VoteOption.voting_status == VoteOptionStatus.CLOSED,
            VoteOption.resolution_type == ObjectionResolutionType.MALICIOUS,
            VoteOption.closed_at.is_not(None),  # type: ignore[union-attr]
        )
        count_statement = (
            select(func.count(VoteOption.id))
            .join(VoteSession, VoteSession.id == VoteOption.session_id)  # type: ignore[arg-type]
            .where(*filters)
        )
        total = (await self.session.exec(count_statement)).one()

        details_statement = (
            select(VoteOption, VoteSession)
            .join(VoteSession, VoteSession.id == VoteOption.session_id)  # type: ignore[arg-type]
            .where(*filters)
            .order_by(VoteOption.closed_at.desc(), VoteOption.id.desc())  # type: ignore
            .limit(limit)
        )
        rows = (await self.session.exec(details_statement)).all()
        records = [
            ObjectionViolationRecordDto(
                option_id=option.id,  # type: ignore[arg-type]
                choice_text=option.choice_text,
                resolution_description=option.resolution_description,
                created_at=option.created_at,
                closed_at=option.closed_at,  # type: ignore[arg-type]
                guild_id=session.guild_id,
                thread_id=session.context_thread_id,
                context_message_id=session.context_message_id,
            )
            for option, session in rows
        ]
        return total, records

    async def delete_option(self, option_id: int):
        """逻辑删除特定选项"""
        option = await self.session.get(VoteOption, option_id)
        if option:
            if option.voting_status != VoteOptionStatus.ACTIVE:
                raise ValueError("已结束的投票选项不能删除。")
            option.data_status = 0
            self.session.add(option)
            await self.session.flush()
