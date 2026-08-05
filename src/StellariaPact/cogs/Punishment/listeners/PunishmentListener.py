import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.share import StellariaPactBot, UnitOfWork
from StellariaPact.share.enums import PunishmentType

from ..logic.PunishmentLogic import PunishmentLogic

logger = logging.getLogger(__name__)

class PunishmentListener(commands.Cog):
    """
    负责维护禁言缓存，并拦截被禁言用户的发言。
    """
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        # 缓存结构: {thread_id: {user_id: mute_end_time (aware datetime)}}
        self.active_mutes: Dict[int, Dict[int, datetime]] = {}
        # 缓存结构: {user_id: expires_at}
        self.active_proposal_violations: Dict[int, datetime] = {}
        self.logic = PunishmentLogic(bot) # 初始化逻辑层
        self.clear_expired_mutes.start()

    def cog_unload(self):
        self.clear_expired_mutes.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # 恢复各提案讨论帖内仍未到期的独立禁言处罚。
        await self._load_active_mutes_into_cache()
        # 恢复机器人全局范围内仍有效的限时提案违规处罚。
        await self._load_active_proposal_violations_into_cache()

    async def _load_active_mutes_into_cache(self):
        """从数据库恢复各提案讨论帖内仍有效的禁言记录。"""
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
                mute_end = activity.mute_end_time
                if mute_end > now:
                    if activity.context_thread_id not in self.active_mutes:
                        self.active_mutes[activity.context_thread_id] = {}
                    self.active_mutes[activity.context_thread_id][activity.user_id] = mute_end

        count = sum(len(users) for users in self.active_mutes.values())
        logger.info(f"Punishment: 成功加载 {count} 条有效禁言记录。")

    async def _load_active_proposal_violations_into_cache(self):
        """从数据库恢复所有有效的限时提案违规处罚。"""
        self.active_proposal_violations.clear()
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishments = await uow.global_proposal_punishment.get_active_by_type(
                PunishmentType.PROPOSAL_VIOLATION
            )
            active_punishments = [
                (punishment.target_user_id, punishment.expires_at)
                for punishment in punishments
                if punishment.expires_at is not None
            ]
        for target_user_id, expires_at in active_punishments:
            self.active_proposal_violations[target_user_id] = expires_at
        logger.info(
            "Punishment: 成功加载 %s 条有效全局提案违规处罚。",
            len(self.active_proposal_violations),
        )

    @tasks.loop(minutes=5)
    async def clear_expired_mutes(self):
        """清理已过期的禁言记录"""
        now = datetime.now(timezone.utc)
        expired = []
        for thread_id, users in list(self.active_mutes.items()):
            for user_id, end_time in list(users.items()):
                if now >= end_time:
                    del self.active_mutes[thread_id][user_id]
                    expired.append((user_id, thread_id))
            if not self.active_mutes[thread_id]:
                del self.active_mutes[thread_id]

        if expired:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.user_activity.batch_clear_expired_mutes(expired)
                await uow.commit()
            logger.info(f"Punishment: 已自动清理 {len(expired)} 条过期的禁言记录。")

        expired_global = [
            user_id
            for user_id, expires_at in self.active_proposal_violations.items()
            if now >= expires_at
        ]
        for user_id in expired_global:
            del self.active_proposal_violations[user_id]
        if expired_global:
            logger.info(
                "Punishment: 已从缓存清理 %s 条到期的全局提案处罚。",
                len(expired_global),
            )

    @commands.Cog.listener()
    async def on_punishment_remove_request(
        self, interaction, thread, moderator, target_user, reason
    ):
        """解除提案内处罚"""
        await self.logic.handle_remove_punishment(
            interaction, thread, moderator, target_user, reason
        )

    @commands.Cog.listener()
    async def on_thread_mute_updated(
        self,
        thread_id: int,
        user_id: int,
        mute_end_time: Optional[datetime],
    ):
        """监听配置更新，实时同步缓存"""
        if thread_id not in self.active_mutes:
            self.active_mutes[thread_id] = {}

        if mute_end_time and mute_end_time > datetime.now(timezone.utc):
            self.active_mutes[thread_id][user_id] = mute_end_time
            logger.debug(
                f"Punishment: 缓存更新 -> 用户 {user_id} "
                f"在帖子 {thread_id} 禁言至 {mute_end_time}"
            )
        elif user_id in self.active_mutes[thread_id]:
            del self.active_mutes[thread_id][user_id]
            logger.debug(f"Punishment: 缓存更新 -> 用户 {user_id} 在帖子 {thread_id} 禁言已解除")

    @commands.Cog.listener()
    async def on_proposal_violation_punishment_updated(
        self,
        user_id: int,
        expires_at: Optional[datetime],
    ):
        """在处罚创建、覆盖或解除后即时同步全局发言限制缓存。"""
        if expires_at and expires_at > datetime.now(timezone.utc):
            self.active_proposal_violations[user_id] = expires_at
        else:
            self.active_proposal_violations.pop(user_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """物理删除被禁言用户的消息"""
        if (
            message.author.bot
            or not isinstance(message.channel, discord.Thread)
            or not message.guild
        ):
            return

        now = datetime.now(timezone.utc)
        thread_mutes = self.active_mutes.get(message.channel.id, {})
        mute_end_time = thread_mutes.get(message.author.id)
        should_delete = mute_end_time is not None and now < mute_end_time

        global_end_time = self.active_proposal_violations.get(message.author.id)
        if not should_delete and global_end_time is not None and now < global_end_time:
            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal = await uow.proposal.get_proposal_by_thread_id(message.channel.id)
            should_delete = proposal is not None

        if should_delete:
            try:
                await message.delete()
                logger.info(
                    f"Punishment: 已拦截并删除用户 {message.author.id} "
                    f"在帖子 {message.channel.id} 中的违规发言。"
                )
            except discord.Forbidden:
                logger.warning(
                    f"Punishment: 机器人缺少管理消息权限，"
                    f"无法删除用户 {message.author.id} 的消息。"
                )
            except discord.NotFound:
                pass
