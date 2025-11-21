import re

import discord


class StringUtils:
    """
    提供字符串处理相关的静态工具方法
    """

    @staticmethod
    def clean_title(title: str) -> str:
        """
        清理帖子标题，移除特定格式的状态前缀。<br>
        例如：'[公示] xxxx' -> 'xxxx'
              '【执行中】 xxxx' -> 'xxxx'
        """
        return re.sub(r"^\s*([\[【].*?[\]】])\s*", "", title).strip()

    @staticmethod
    def extract_thread_id_from_url(url: str) -> int | None:
        """
        从 Discord 帖子链接中提取帖子 ID
        """
        match = re.search(r"/(\d+)$", url)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def extract_proposer_id_from_content(content: str) -> int | None:
        """
        从帖子内容中提取发起人ID <br>
        例如，匹配 "发起人: <@12345>" 或 "提案人: <@12345>"。
        """
        # 正则表达式匹配 "发起人" 或 "提案人"，后面跟着冒号（全角或半角）和空格，然后是用户提及
        match = re.search(r"(?:发起人|提案人)\s*[:：]\s*<@!?(\d+)>", content)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    async def extract_starter_content(thread: discord.Thread) -> str | None:
        """
        提取帖子首楼的内容

        Args:
            thread (discord.Thread): 目标帖子

        Returns:
            str | None: 首楼内容，如果无法获取则返回 None
        """
        try:
            # 首先尝试获取帖子的启动消息
            starter_message = thread.starter_message
            if not starter_message:
                # 如果启动消息不可用，则通过API获取
                starter_message = await thread.fetch_message(thread.id)

            if starter_message:
                return starter_message.content
            return None
        except Exception:
            return None

    @staticmethod
    def clean_proposal_content(content: str) -> str:
        """
        使用正则提取提案内容
        """
        # 移除 "提案人: <@...>"
        cleaned_content = re.sub(
            r"^\s*\*{2,}\s*(?:发起人|提案人)\s*[:：]\s*<@!?\d+>\s*\*{3}\s*[\r\n]*",
            "",
            content,
        )

        # 移除 "讨论帖创建时间: <t:...>"
        cleaned_content = re.sub(
            r"[\r\n]*\s*\*{1,}\s*讨论帖创建时间\s*[:：]\s*<t:\d+:[a-zA-Z]>\s*\*\s*\Z",
            "",
            cleaned_content,
        )

        # 匹配 "> ## xxx", 替换成更适合在 embed 中显示的
        cleaned_content = re.sub(
            r"[\r\n]*\>\s*\#{2,}\s*",
            "\n> ### ",
            cleaned_content,
        )
        return cleaned_content.strip()
