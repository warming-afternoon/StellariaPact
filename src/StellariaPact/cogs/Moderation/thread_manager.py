import logging
import discord
from StellariaPact.share.DiscordUtils import DiscordUtils
from StellariaPact.share.StringUtils import StringUtils

logger = logging.getLogger(__name__)


class ProposalThreadManager:
    """
    用于管理议事提案帖子外观（标题、标签、状态）
    """

    def __init__(self, config: dict):
        self.config = config
        self.status_map = {
            "discussion": {
                "prefix": "[讨论中]",
                "tag_name": "discussion",
                "archive": False,
                "lock": False,
            },
            "executing": {
                "prefix": "[执行中]",
                "tag_name": "executing",
                "archive": False,
                "lock": False,
            },
            "frozen": {
                "prefix": "[冻结中]",
                "tag_name": "frozen",
                "archive": True,
                "lock": True,
            },
            "finished": {
                "prefix": "[已结束]",
                "tag_name": "finished",
                "archive": True,
                "lock": True,
            },
            "abandoned": {
                "prefix": "[已废弃]",
                "tag_name": "abandoned",
                "archive": True,
                "lock": True,
            },
            "rejected": {
                "prefix": "[已否决]",
                "tag_name": "rejected",
                "archive": True,
                "lock": True,
            },
        }

    async def update_status(self, thread: discord.Thread, new_status_key: str):
        """
        根据给定的状态关键字，更新帖子的标题、标签、归档和锁定状态。

        Args:
            thread: 目标 discord.Thread 对象。
            new_status_key: self.status_map 中的一个键，如 'discussion', 'finished' 等。
        """
        status_info = self.status_map.get(new_status_key)
        if not status_info:
            logger.warning(f"未知的提案状态关键字: '{new_status_key}'，无法更新帖子 {thread.id}。")
            return

        clean_title = StringUtils.clean_title(thread.name)
        new_title = f"{status_info['prefix']} {clean_title}"

        edit_payload = {}

        if new_title != thread.name:
            edit_payload["name"] = new_title

        if isinstance(thread.parent, discord.ForumChannel):
            new_tags = DiscordUtils.calculate_new_tags(
                current_tags=thread.applied_tags,
                forum_tags=thread.parent.available_tags,
                config=self.config,
                target_tag_name=status_info["tag_name"],
            )
            if new_tags is not None:
                edit_payload["applied_tags"] = new_tags

        if thread.archived != status_info["archive"]:
            edit_payload["archived"] = status_info["archive"]

        if thread.locked != status_info["lock"]:
            edit_payload["locked"] = status_info["lock"]

        if not edit_payload:
            logger.info(f"帖子 {thread.id} 的状态已经是 '{new_status_key}'，无需更新。")
            return

        try:
            await thread.edit(**edit_payload)
            logger.info(f"已将帖子 {thread.id} 的状态更新为 '{new_status_key}'。")
        except discord.errors.Forbidden:
            logger.error(
                f"机器人缺少权限，无法更新帖子 {thread.id} 的状态为 '{new_status_key}'。"
                "请检查机器人是否具有'管理帖子'权限。"
            )
        except Exception as e:
            logger.error(f"更新帖子 {thread.id} 时发生未知错误: {e}", exc_info=True)