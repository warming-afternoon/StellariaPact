from typing import List, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.VoteOption import VoteOption


class VoteOptionService:
    """
    提供处理投票选项 (`VoteOption`) 相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_vote_options(self, session_id: int, options: List[str]):
        """为指定的会话创建投票选项"""
        for i, text in enumerate(options):
            new_option = VoteOption(session_id=session_id, choice_index=i + 1, choice_text=text)
            self.session.add(new_option)
        await self.session.flush()

    async def get_vote_options(self, session_id: int) -> Sequence[VoteOption]:
        """获取指定会话的所有投票选项"""
        statement = (
            select(VoteOption)
            .where(VoteOption.session_id == session_id)  # type: ignore
            .order_by(VoteOption.choice_index)  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.all()
