from __future__ import annotations

from StellariaPact.share.ProposalContentFormatter import ProposalContentFormatter


class UpdateProposalContentDto:
    """
    更新提案内容的数据传输对象。
    用于从 Modal 传递数据到处理逻辑。
    """

    def __init__(
        self,
        proposal_id: int,
        proposer_id: int,
        title: str,
        reason: str,
        motion: str,
        implementation: str,
        executor: str,
        thread_id: int,
    ):
        self.proposal_id = proposal_id
        self.proposer_id = proposer_id
        self.title = title
        self.reason = reason
        self.motion = motion
        self.implementation = implementation
        self.executor = executor
        self.thread_id = thread_id

    def format_content(self) -> str:
        """将各个字段格式化为提案内容字符串。"""
        return ProposalContentFormatter.format_discussion_body(
            author_id=self.proposer_id,
            reason=self.reason,
            motion=self.motion,
            implementation=self.implementation,
            executor=self.executor,
            heading_level=2,
        )
