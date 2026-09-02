import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.share import StellariaPactBot, safeDefer

from ..logic.PunishmentLogic import PunishmentLogic
from .PunishmentEmbedBuilder import PunishmentEmbedBuilder

logger = logging.getLogger(__name__)

MAX_PUNISHMENT_EVIDENCE_FILES = 5


class PunishmentModal(discord.ui.Modal):
    """
    用于配置或修改用户处罚的模态框。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        target_user: discord.User | discord.Member,
        target_message: Optional[discord.Message] = None,
        existing_activity: Optional[UserActivity] = None,
    ):
        is_edit = existing_activity is not None
        super().__init__(title="修改处罚设置" if is_edit else "踢出/处罚提案成员", timeout=1700)

        self.bot = bot
        self.logic = PunishmentLogic(bot)
        self.target_user = target_user
        self.target_message = target_message

        # 计算预填数据
        default_voting = "是"
        default_mute_minutes = "0"

        if existing_activity:
            default_voting = "是" if existing_activity.validation == 1 else "否"
            if existing_activity.mute_end_time:
                mute_end = existing_activity.mute_end_time
                now = datetime.now(timezone.utc)
                if mute_end > now:
                    delta_minutes = int((mute_end - now).total_seconds() / 60)
                    default_mute_minutes = str(delta_minutes)

        self.allow_voting_input = discord.ui.TextInput(
            label="是否保留投票权 (是/否)",
            placeholder="默认为“否”(剥夺投票权)。",
            required=True,
            default=default_voting,
        )
        self.add_item(self.allow_voting_input)

        self.mute_duration_input = discord.ui.TextInput(
            label="禁言时长 (自当前起算分钟数)",
            placeholder="例如 60 (代表禁言1小时)。0代表解除禁言/不禁言。",
            required=True,
            default=default_mute_minutes,
        )
        self.add_item(self.mute_duration_input)

        self.reason_input = discord.ui.TextInput(
            label="操作原因",
            style=discord.TextStyle.long,
            placeholder="请输入您执行或修改此处罚的理由，这将用于频道公示...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_input)

        self.evidence_upload = discord.ui.FileUpload(
            required=False,
            min_values=0,
            max_values=MAX_PUNISHMENT_EVIDENCE_FILES,
        )
        self.add_item(
            discord.ui.Label(
                text="处罚材料（可选）",
                description="最多上传 5 个文件，仅发送到处罚公示区。",
                component=self.evidence_upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        try:
            # 解析数据
            allow_voting_str = self.allow_voting_input.value.strip()
            if allow_voting_str == "是":
                is_voting_allowed = True
            elif allow_voting_str == "否":
                is_voting_allowed = False
            else:
                return await interaction.followup.send(
                    "“是否保留投票权”字段必须输入“是”或“否”。",
                    ephemeral=True,
                )

            try:
                mute_minutes = int(self.mute_duration_input.value)
                if mute_minutes < 0:
                    raise ValueError()
            except ValueError:
                return await interaction.followup.send(
                    "禁言时长必须是一个有效的非负整数。",
                    ephemeral=True,
                )

            reason = self.reason_input.value
            thread = interaction.channel
            moderator = interaction.user

            if not isinstance(thread, discord.Thread) or not isinstance(moderator, discord.Member):
                return

            publicity_channel, publicity_fallback_reason = (
                await self._get_publicity_channel(thread)
            )
            files: list[discord.File] = []
            if publicity_channel is not None:
                try:
                    for attachment in self.evidence_upload.values:
                        files.append(await attachment.to_file())
                except Exception:
                    for file in files:
                        file.close()
                    raise

            # 计算截止时间（UTC aware datetime）
            mute_end_time = None
            if mute_minutes > 0:
                mute_end_time = datetime.now(timezone.utc) + timedelta(minutes=mute_minutes)

            # 资格状态、处罚记录和进行中投票的清理在同一事务内完成。
            try:
                result = await self.logic.apply_thread_punishment(
                    guild_id=thread.guild.id,
                    thread_id=thread.id,
                    target_user_id=self.target_user.id,
                    moderator_id=moderator.id,
                    reason=reason,
                    source_message_url=(
                        self.target_message.jump_url if self.target_message is not None else None
                    ),
                    voting_allowed=is_voting_allowed,
                    mute_end_time=mute_end_time,
                )
            except Exception:
                for file in files:
                    file.close()
                raise

            # 派发事件更新内存缓存
            self.bot.dispatch(
                "thread_mute_updated",
                thread.id,
                self.target_user.id,
                mute_end_time,
            )
            for vote_details in result.vote_details_to_update:
                self.bot.dispatch("vote_details_updated", vote_details)

            if publicity_channel is None:
                fallback_embed = PunishmentEmbedBuilder.create_punishment_embed(
                    moderator=moderator,
                    target_user=self.target_user,
                    reason=reason,
                    target_message=self.target_message,
                    is_voting_allowed=is_voting_allowed,
                    mute_end_time=mute_end_time,
                )
                try:
                    await self.bot.api_scheduler.submit(
                        thread.send(embed=fallback_embed),
                        priority=5,
                    )
                    material_warning = (
                        "；上传的处罚材料未发布"
                        if self.evidence_upload.values
                        else ""
                    )
                    await interaction.followup.send(
                        f"处罚已生效，并已降级为原帖单处公示{material_warning}。"
                        f"原因：{publicity_fallback_reason}",
                        ephemeral=True,
                    )
                except Exception:
                    logger.exception("帖子内处罚已生效，但降级公示发送失败。")
                    await interaction.followup.send(
                        "处罚已生效，但处罚公示区不可用且原帖公示发送失败，请人工补发。",
                        ephemeral=True,
                    )
                return

            public_embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=self.target_user,
                reason=reason,
                target_message=None,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=mute_end_time,
            )
            original_thread_state: tuple[bool, bool] | None = None
            unlocked_for_publicity = False
            try:
                if (
                    isinstance(publicity_channel, discord.Thread)
                    and publicity_channel.locked is True
                ):
                    original_thread_state = (
                        publicity_channel.archived,
                        publicity_channel.locked,
                    )
                    try:
                        publicity_channel = await self.bot.api_scheduler.submit(
                            publicity_channel.edit(
                                locked=False,
                                archived=False,
                                reason="发送帖子内处罚正式公示",
                            ),
                            priority=5,
                        )
                        unlocked_for_publicity = True
                    except Exception:
                        logger.exception(
                            "帖子内处罚已生效，但处罚公示子区自动解锁失败。"
                        )
                        await interaction.followup.send(
                            "处罚已生效，但处罚公示子区自动解锁失败；"
                            "原帖未发布无效跳转链接，请人工处理。",
                            ephemeral=True,
                        )
                        return

                send_kwargs: dict[str, object] = {"embed": public_embed}
                if files:
                    send_kwargs["files"] = files
                public_message = await self.bot.api_scheduler.submit(
                    publicity_channel.send(**send_kwargs),
                    priority=5,
                )
            except Exception:
                logger.exception("帖子内处罚已生效，但处罚公示区发送失败。")
                state_recovery_message = ""
                if unlocked_for_publicity and original_thread_state is not None:
                    original_archived, original_locked = original_thread_state
                    try:
                        await self.bot.api_scheduler.submit(
                            publicity_channel.edit(
                                locked=original_locked,
                                archived=original_archived,
                                reason="处罚公示发送失败，恢复子区原状态",
                            ),
                            priority=5,
                        )
                        state_recovery_message = "；公示子区已恢复原来的锁定和归档状态"
                    except Exception:
                        logger.exception("处罚公示发送失败后，恢复子区原状态失败。")
                        state_recovery_message = "；公示子区也未能恢复原来的锁定和归档状态"
                await interaction.followup.send(
                    f"处罚已生效，但处罚公示区发送失败{state_recovery_message}；"
                    "原帖未发布无效跳转链接，请人工补发。",
                    ephemeral=True,
                )
                return
            finally:
                for file in files:
                    file.close()

            location_saved = True
            try:
                await self.logic.set_thread_punishment_publicity_message(
                    result.punishment_record_id,
                    guild_id=thread.guild.id,
                    channel_id=publicity_channel.id,
                    message_id=public_message.id,
                )
            except Exception:
                location_saved = False
                logger.exception("保存帖子内处罚正式公示位置失败。")

            source_embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=self.target_user,
                reason=reason,
                target_message=None,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=mute_end_time,
                publicity_message_url=public_message.jump_url,
            )
            source_sent = True
            try:
                await self.bot.api_scheduler.submit(thread.send(embed=source_embed), priority=5)
            except Exception:
                source_sent = False
                logger.exception("帖子内处罚正式公示已发送，但原帖公示发送失败。")

            warnings: list[str] = []
            if not location_saved:
                warnings.append("历史记录未能保存正式公示链接")
            if not source_sent:
                warnings.append("原帖公示发送失败")
            if warnings:
                await interaction.followup.send(
                    f"处罚已生效，正式公示已发送；{'；'.join(warnings)}，请人工检查。",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send("已成功处罚并完成双区公示。", ephemeral=True)

        except Exception as e:
            logger.error(f"处理处罚模态框时发生错误: {e}", exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)

    async def _get_publicity_channel(
        self,
        thread: discord.Thread,
    ) -> tuple[discord.TextChannel | discord.Thread | None, str | None]:
        """解析并预检处罚公示区；失败时返回允许降级的原因。"""
        configured = self.bot.config.get("channels", {}).get("punishment_publicity")
        try:
            channel_id = int(configured)
        except (TypeError, ValueError):
            return None, "未配置处罚公示区"

        channel = thread.guild.get_channel_or_thread(channel_id)
        if channel is None:
            try:
                channel = await thread.guild.fetch_channel(channel_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
                discord.InvalidData,
            ):
                logger.exception("无法获取处罚公示频道或子区。")
                return None, "无法获取处罚公示频道或子区"

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None, "处罚公示区不是可用的文字频道或子区"

        bot_member = thread.guild.me
        if bot_member is None:
            return None, "无法解析 Bot 的服务器成员身份"
        permissions = channel.permissions_for(bot_member)
        required_permissions = {
            "view_channel": "查看频道",
            "embed_links": "嵌入链接",
            "attach_files": "上传附件",
        }
        if isinstance(channel, discord.Thread):
            required_permissions["send_messages_in_threads"] = "在子区中发送消息"
            if channel.locked is True and not getattr(permissions, "manage_threads", False):
                return None, "处罚公示子区已锁定且 Bot 无管理子区权限"
        else:
            required_permissions["send_messages"] = "发送消息"
        missing = [
            label
            for attribute, label in required_permissions.items()
            if not getattr(permissions, attribute, False)
        ]
        if missing:
            return None, f"Bot 缺少处罚公示区权限：{'、'.join(missing)}"
        return channel, None
