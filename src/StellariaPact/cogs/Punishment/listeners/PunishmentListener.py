import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord.ext import commands, tasks
from sqlalchemy import select, update

from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.share import StellariaPactBot, UnitOfWork

logger = logging.getLogger(__name__)

class PunishmentListener(commands.Cog):
    """
    负责维护禁言缓存，并拦截被禁言用户的发言。
    """
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        # 缓存结构: {thread_id: {user_id: mute_end_time (aware datetime)}}
        self.active_mutes: Dict[int, Dict[int, datetime]] = {}
        self.clear_expired_mutes.start()

    def cog_unload(self):
        self.clear_expired_mutes.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._load_active_mutes_into_cache()

    async def _load_active_mutes_into_cache(self):
        logger.info("Punishment: 正在加载有效的禁言记录到缓存...")
        self.active_mutes.clear()
        now = datetime.now(timezone.utc)

        async with UnitOfWork(self.bot.db_handler) as uow:
            statement = select(UserActivity).where(
                UserActivity.mute_end_time != None, # noqa: E711 # type: ignore
            )
            results = await uow.session.exec(statement) # type: ignore

            for activity in results.all():
                if not activity.mute_end_time:
                    continue
                # DB 中是 naive UTC，转换为 aware UTC
                mute_end = activity.mute_end_time.replace(tzinfo=timezone.utc)
                if mute_end > now:
                    if activity.context_thread_id not in self.active_mutes:
                        self.active_mutes[activity.context_thread_id] = {}
                    self.active_mutes[activity.context_thread_id][activity.user_id] = mute_end

        count = sum(len(users) for users in self.active_mutes.values())
        logger.info(f"Punishment: 成功加载 {count} 条有效禁言记录。")

    @tasks.loop(minutes=5)
    async def clear_expired_mutes(self):
        """清理已过期的禁言记录"""
        now = datetime.now(timezone.utc)
        expired = []

        # 清理内存
        for thread_id, users in list(self.active_mutes.items()):
            for user_id, end_time in list(users.items()):
                if now >= end_time:
                    del self.active_mutes[thread_id][user_id]
                    expired.append((user_id, thread_id))
            if not self.active_mutes[thread_id]:
                del self.active_mutes[thread_id]

        # 清理数据库
        if expired:
            async with UnitOfWork(self.bot.db_handler) as uow:
                for user_id, thread_id in expired:
                    stmt = (
                        update(UserActivity)
                        .where(
                            UserActivity.user_id == user_id,
                            UserActivity.context_thread_id == thread_id,
                        )
                        .values(mute_end_time=None)
                    )
                    await uow.session.execute(stmt)
                await uow.commit()
            logger.info(f"Punishment: 已自动清理 {len(expired)} 条过期的禁言记录。")

    @commands.Cog.listener()
    async def on_thread_mute_updated(self, thread_id: int, user_id: int, mute_end_time: Optional[datetime]):
        """监听配置更新，实时同步缓存"""
        if thread_id not in self.active_mutes:
            self.active_mutes[thread_id] = {}

        if mute_end_time and mute_end_time > datetime.now(timezone.utc):
            self.active_mutes[thread_id][user_id] = mute_end_time
            logger.debug(f"Punishment: 缓存更新 -> 用户 {user_id} 在帖子 {thread_id} 禁言至 {mute_end_time}")
        elif user_id in self.active_mutes[thread_id]:
            del self.active_mutes[thread_id][user_id]
            logger.debug(f"Punishment: 缓存更新 -> 用户 {user_id} 在帖子 {thread_id} 禁言已解除")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """物理删除被禁言用户的消息"""
        if message.author.bot or not isinstance(message.channel, discord.Thread) or not message.guild:
            return

        thread_mutes = self.active_mutes.get(message.channel.id)
        if not thread_mutes:
            return

        mute_end_time = thread_mutes.get(message.author.id)
        if not mute_end_time:
            return

        if datetime.now(timezone.utc) < mute_end_time:
            try:
                await message.delete()
                logger.info(f"Punishment: 已拦截并删除用户 {message.author.id} 在帖子 {message.channel.id} 中的违规发言。")
            except discord.Forbidden:
                logger.warning(f"Punishment: 机器人缺少管理消息权限，无法删除用户 {message.author.id} 的消息。")
            except discord.NotFound:
                pass
