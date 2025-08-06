import logging
from typing import List, Optional, Sequence

import discord

from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class DiscordUtils:
    """
    提供 Discord API 相关的静态工具方法。
    """

    @staticmethod
    async def fetch_channel(
        bot: StellariaPactBot, channel_id: int
    ) -> discord.TextChannel | discord.ForumChannel:
        """
        安全地获取一个频道，优先使用缓存，支持文本和论坛频道。

        Args:
            bot: Bot 实例。
            channel_id: 要获取的频道的 ID。

        Returns:
            获取到的频道对象。

        Raises:
            RuntimeError: 如果无法获取频道，或者频道不是文本或论坛频道。
        """
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as e:
                raise RuntimeError(f"无法获取ID为 {channel_id} 的频道。") from e

        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            raise RuntimeError(f"ID 为 {channel_id} 的频道不是一个文本或论坛频道。")
        return channel

    @staticmethod
    async def fetch_thread(bot: StellariaPactBot, thread_id: int) -> Optional[discord.Thread]:
        """
        安全地获取一个帖子，优先使用缓存。

        Args:
            bot: Bot 实例。
            thread_id: 要获取的帖子的 ID。

        Returns:
            获取到的帖子对象，如果未找到则返回 None。
        """
        thread = bot.get_channel(thread_id)
        if isinstance(thread, discord.Thread):
            return thread
        try:
            thread = await bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread
            return None
        except (discord.NotFound, discord.Forbidden):
            logger.warning(f"无法获取ID为 {thread_id} 的帖子。")
            return None

    @staticmethod
    def calculate_new_tags(
        current_tags: Sequence[discord.ForumTag],
        forum_tags: Sequence[discord.ForumTag],
        config: dict,
        target_tag_name: str,
    ) -> Optional[List[discord.ForumTag]]:
        """
        计算帖子的新标签列表。

        Args:
            current_tags: 帖子当前的标签列表。
            forum_tags: 论坛频道所有可用的标签列表。
            config: 包含标签ID和状态标签键列表的配置字典。
            target_tag_name: 要添加的目标标签在 config 中的键名。

        Returns:
            计算出的新标签列表，如果无需更改则返回 None。
        """
        # 获取目标标签对象
        target_tag_id_str = config.get("tags", {}).get(target_tag_name)
        if not target_tag_id_str:
            logger.warning(f"未在 config.json 中配置 '{target_tag_name}' 标签ID。")
            return None

        target_tag_id = int(target_tag_id_str)
        target_tag = next((t for t in forum_tags if t.id == target_tag_id), None)

        if not target_tag:
            logger.warning(f"在论坛中找不到ID为 {target_tag_id} 的目标标签。")
            return None

        # 从配置中获取要移除的状态标签键列表
        status_tag_keys = config.get("status_tag_keys", [])
        if not status_tag_keys:
            logger.warning("未在 config.json 中配置 'status_tag_keys'。")
            # 即使没有配置 status_tag_keys，也继续执行，只是不移除任何标签

        status_tag_ids = {
            int(config.get("tags", {}).get(key))
            for key in status_tag_keys
            if config.get("tags", {}).get(key)
        }

        # 移除所有状态标签，然后添加目标标签
        new_tags = [t for t in current_tags if t.id not in status_tag_ids]
        if target_tag not in new_tags:
            new_tags.append(target_tag)

        # 如果标签列表没有变化，则返回 None
        if set(t.id for t in new_tags) == set(t.id for t in current_tags):
            return None

        return new_tags
