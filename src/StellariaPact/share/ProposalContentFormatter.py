from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto


class ProposalContentFormatter:
    """提案内容文本格式化工具，统一讨论帖和审核帖的文本模板。"""

    @staticmethod
    def format_discussion_body(
        author_id: int,
        reason: str,
        motion: str,
        implementation: str,
        executor: str,
        *,
        heading_level: int = 2,
        include_header: bool = True,
    ) -> str:
        """生成讨论帖正文（***提案人:*** + > ## 格式），不含尾部附加信息。"""
        h = "#" * heading_level
        header = f"***提案人: <@{author_id}>***\n\n" if include_header else ""
        return (
            f"{header}"
            f"> {h} 提案原因\n{reason}\n\n"
            f"> {h} 议案动议\n{motion}\n\n"
            f"> {h} 执行方案\n{implementation}\n\n"
            f"> {h} 议案执行人\n{executor}"
        )

    @staticmethod
    def format_review_body(
        intake: ProposalIntakeDto,
        submitted_ts: int,
        *,
        id_label: str = "草案ID",
    ) -> str:
        """生成审核帖正文（表情符号标签格式），不含状态行和审核意见行。"""
        return (
            f"👤 **提案人：** <@{intake.author_id}>\n"
            f"📅 **提交时间：** <t:{submitted_ts}:f>\n"
            f"🆔 **{id_label}：** `{intake.id}`\n\n"
            "---\n\n"
            f"🏷️ **议案标题**\n{intake.title}\n\n"
            f"📝 **提案原因**\n{intake.reason}\n\n"
            f"📋 **议案动议**\n{intake.motion}\n\n"
            f"🔧 **执行方案**\n{intake.implementation}\n\n"
            f"👨‍💼 **议案执行人**\n{intake.executor}\n\n"
            "---"
        )
