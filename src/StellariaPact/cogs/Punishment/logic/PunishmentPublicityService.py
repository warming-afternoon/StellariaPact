import logging

import discord

from StellariaPact.share import StellariaPactBot

from ..dto.PublicityChannelDto import PublicityChannelDto
from ..dto.PunishmentPublicityDto import PunishmentPublicityDto
from ..qo.PublishPunishmentQo import PublishPunishmentQo
from ..qo.ResolvePublicityChannelQo import ResolvePublicityChannelQo

logger = logging.getLogger(__name__)


class PunishmentPublicityService:
    """统一处理处罚公示频道预检、子区解锁与正式消息发送。"""

    def __init__(self, bot: StellariaPactBot):
        """保存用于频道查询和接口调度的机器人依赖。"""
        self.bot = bot

    async def resolve_channel(self, qo: ResolvePublicityChannelQo) -> PublicityChannelDto:
        """解析并预检处罚公示区，返回频道或允许降级的原因。"""
        # 读取配置中的公示频道标识。
        configured = self.bot.config.get("channels", {}).get("punishment_publicity")
        try:
            channel_id = int(configured)
        except (TypeError, ValueError):
            return PublicityChannelDto(fallback_reason="未配置处罚公示区")

        # 优先使用服务器缓存，未命中时只查询一次频道。
        channel = qo.guild.get_channel_or_thread(channel_id)
        if channel is None:
            try:
                channel = await qo.guild.fetch_channel(channel_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
                discord.InvalidData,
            ):
                logger.exception("无法获取处罚公示频道或子区。")
                return PublicityChannelDto(fallback_reason="无法获取处罚公示频道或子区")

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return PublicityChannelDto(fallback_reason="处罚公示区不是可用的文字频道或子区")

        # 根据频道类型检查发送权限及锁定子区的管理权限。
        bot_member = qo.guild.me
        if bot_member is None:
            return PublicityChannelDto(fallback_reason="无法解析 Bot 的服务器成员身份")
        permissions = channel.permissions_for(bot_member)
        required_permissions = {
            "view_channel": "查看频道",
            "embed_links": "嵌入链接",
            "attach_files": "上传附件",
        }
        if isinstance(channel, discord.Thread):
            required_permissions["send_messages_in_threads"] = "在子区中发送消息"
            if channel.locked is True and not getattr(permissions, "manage_threads", False):
                return PublicityChannelDto(
                    fallback_reason="处罚公示子区已锁定且 Bot 无管理子区权限"
                )
        else:
            required_permissions["send_messages"] = "发送消息"
        missing = [
            label
            for attribute, label in required_permissions.items()
            if not getattr(permissions, attribute, False)
        ]
        if missing:
            return PublicityChannelDto(
                fallback_reason=f"Bot 缺少处罚公示区权限：{'、'.join(missing)}"
            )
        return PublicityChannelDto(channel=channel)

    async def publish(self, qo: PublishPunishmentQo) -> PunishmentPublicityDto:
        """解锁公示子区并发送正式消息，发送失败时恢复子区原状态。"""
        channel = qo.channel
        original_state: tuple[bool, bool] | None = None

        # 记录锁定子区的原状态，成功发送后保持开放以便继续转发证据。
        if isinstance(channel, discord.Thread) and channel.locked is True:
            original_state = (channel.archived, channel.locked)
            try:
                channel = await self.bot.api_scheduler.submit(
                    channel.edit(
                        locked=False,
                        archived=False,
                        reason="发送帖子内处罚正式公示",
                    ),
                    priority=5,
                )
            except Exception:
                logger.exception("处罚公示子区自动解锁失败。")
                return PunishmentPublicityDto(
                    channel=channel,
                    error="处罚已生效，但处罚公示子区自动解锁失败；"
                    "原帖未发布无效跳转链接，请人工处理。",
                )

        # 仅在正式消息发送成功后向调用方返回可用于原帖跳转的消息。
        try:
            send_kwargs: dict[str, object] = {"embed": qo.embed}
            if qo.files:
                send_kwargs["files"] = list(qo.files)
            message = await self.bot.api_scheduler.submit(
                channel.send(**send_kwargs), priority=5
            )
            return PunishmentPublicityDto(channel=channel, message=message)
        except Exception:
            logger.exception("处罚公示区发送失败。")

        # 正式消息发送失败时恢复原状态，并让调用方提示管理员处理。
        recovery_message = ""
        if original_state is not None:
            original_archived, original_locked = original_state
            try:
                await self.bot.api_scheduler.submit(
                    channel.edit(
                        locked=original_locked,
                        archived=original_archived,
                        reason="处罚公示发送失败，恢复子区原状态",
                    ),
                    priority=5,
                )
                recovery_message = "；公示子区已恢复原来的锁定和归档状态"
            except Exception:
                logger.exception("处罚公示发送失败后，恢复子区原状态失败。")
                recovery_message = "；公示子区也未能恢复原来的锁定和归档状态"
        return PunishmentPublicityDto(
            channel=channel,
            error=f"处罚已生效，但处罚公示区发送失败{recovery_message}；"
            "原帖未发布无效跳转链接，请人工补发。",
        )
