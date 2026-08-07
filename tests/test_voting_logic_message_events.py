from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.repository.VoteSessionRepository import VoteSessionRepository


@pytest.mark.asyncio
async def test_vote_panel_details_use_one_bulk_option_query() -> None:
    """验证撤票后的面板详情不会按会话逐条查询投票选项。"""
    # 构造刷新前后的会话快照和对应投票选项。
    sessions_before = [MagicMock(id=11), MagicMock(id=12)]
    sessions_after = [MagicMock(id=11), MagicMock(id=12)]
    option_for_first = MagicMock(session_id=11)
    option_for_second = MagicMock(session_id=12)

    # 模拟工作单元中的批量删除、刷新和批量查询能力。
    uow = MagicMock()
    uow.vote_session.get_all_sessions_in_thread_with_details = AsyncMock(
        side_effect=[sessions_before, sessions_after]
    )
    uow.user_vote.delete_all_user_votes_in_thread = AsyncMock(return_value=2)
    uow.flush = AsyncMock()
    uow.vote_option.get_vote_options_by_session_ids = AsyncMock(
        return_value=[option_for_first, option_for_second]
    )

    # 隔离 DTO 构造，专门验证查询次数和分组结果。
    with patch.object(
        VoteSessionRepository,
        "get_vote_details_dto",
        side_effect=["first-detail", "second-detail"],
    ) as build_details:
        result = await VotingLogic.remove_active_user_votes_in_thread(
            uow=uow,
            user_id=500,
            thread_id=400,
        )

    # 投票选项只批量查询一次，随后按会话在内存中组合。
    uow.vote_option.get_vote_options_by_session_ids.assert_awaited_once_with([11, 12])
    assert build_details.call_args_list == [
        call(sessions_after[0], [option_for_first]),
        call(sessions_after[1], [option_for_second]),
    ]
    assert result == ["first-detail", "second-detail"]
