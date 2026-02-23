from __future__ import annotations


class UpdateProposalContentDto:
    """
    更新提案内容的数据传输对象。
    用于从 Modal 传递数据到处理逻辑。
    """

    def __init__(
        self,
        proposal_id: int,
        title: str,
        reason: str,
        motion: str,
        implementation: str,
        executor: str,
        thread_id: int,
    ):
        self.proposal_id = proposal_id
        self.title = title
        self.reason = reason
        self.motion = motion
        self.implementation = implementation
        self.executor = executor
        self.thread_id = thread_id

    def format_content(self) -> str:
        """
        将各个字段格式化为提案内容字符串。
        """
        return (
            f"### 提案原因\n\n{self.reason}\n\n"
            f"### 议案动议\n\n{self.motion}\n\n"
            f"### 执行方案\n\n{self.implementation}\n\n"
            f"### 议案执行人\n\n{self.executor}"
        )
