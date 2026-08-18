from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.share import BaseDto


class StructuredSpeechDeletionResultDto(BaseDto):
    """表示结构化消息删除后需要刷新的投票数据。"""

    thread_id: int
    """表示需要刷新投票面板的讨论帖子 ID。"""

    vote_details: list[VoteDetailDto]
    """表示因用户资格变化而需要刷新的投票详情。"""
