import re


class StringUtils:
    """
    提供字符串处理相关的静态工具方法。
    """

    @staticmethod
    def clean_title(title: str) -> str:
        """
        清理帖子标题，移除特定格式的状态前缀。
        例如：'[公示] xxxx' -> 'xxxx'
              '【执行中】 xxxx' -> 'xxxx'
        """
        return re.sub(r"^\s*([\[【].*?[\]】])\s*", "", title).strip()
