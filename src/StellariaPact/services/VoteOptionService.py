from typing import List, Optional, Sequence

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.VoteOption import VoteOption


class VoteOptionService:
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
                data_status=1
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
            data_status=1
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

    async def get_options_by_session_ids(self, session_ids: list[int], option_type: int) -> Sequence[VoteOption]:
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

    async def delete_option(self, option_id: int):
        """逻辑删除特定选项"""
        option = await self.session.get(VoteOption, option_id)
        if option:
            option.data_status = 0
            self.session.add(option)
            await self.session.flush()
