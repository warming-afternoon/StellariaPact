from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from StellariaPact.cogs.Intake.IntakeModal import IntakeModal
from StellariaPact.share.SafeDefer import safeDefer

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

    from ..Cog import IntakeCog
    from ..dto.IntakeSubmissionDto import IntakeSubmissionDto


logger = logging.getLogger(__name__)


class IntakeEventListenerCog(commands.Cog):
    """
    专门用于监听和处理与草案相关的事件的 Cog。
    """

    def __init__(self, bot: StellariaPactBot, intake_cog: IntakeCog):
        self.bot = bot
        self.intake_cog = intake_cog

    @commands.Cog.listener()
    async def on_intake_submission_requested(self, interaction: discord.Interaction):
        logger.info(f"接收到打开草案表单事件，请求人: {interaction.user.id}")

        allowed, message = await self.intake_cog.logic.check_submission_limit(
            interaction.guild_id or 0
        )
        if not allowed:
            await interaction.response.send_message(message, ephemeral=True)
            return

        draft = self.intake_cog.logic.get_draft(interaction.user.id)
        await interaction.response.send_modal(IntakeModal(draft))

    @commands.Cog.listener()
    async def on_intake_submitted(
        self,
        interaction: discord.Interaction,
        dto: IntakeSubmissionDto,
    ):
        await safeDefer(interaction, ephemeral=True)
        logger.info(f"接收到草案提交事件，提交人: {dto.author_id}")

        self.intake_cog.logic.save_draft(dto.author_id, dto)

        try:
            intake_dto = await self.intake_cog.logic.process_submit_intake(dto)
            self.intake_cog.logic.clear_draft(dto.author_id)
            logger.info(
                f"✅ 议案草稿 (ID: {intake_dto.id}) by {dto.author_id} "
                "已成功提交至审核通道。"
            )
            await interaction.followup.send("✅ 草案已提交", ephemeral=True)
        except PermissionError as pe:
            logger.warning(f"提交草案被拒绝 (讨论中议案过多): {dto.author_id}")
            await interaction.followup.send(f"❌ {str(pe)}", ephemeral=True)
        except Exception as e:
            logger.error(f"处理来自 {dto.author_id} 的草案提交时出错: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ 提交过程中发生未知错误。您的草稿已保留 30 分钟，请稍后重试。\n{e}",
                ephemeral=True,
            )

    @commands.Cog.listener()
    async def on_intake_approved(
        self,
        interaction: discord.Interaction,
        review_comment: str,
    ):
        logger.info(
            f"接收到草案批准事件，审核人: {interaction.user.id}, "
            f"审核意见: {review_comment[:50]}..."
        )
        await safeDefer(interaction, ephemeral=True)

        try:
            assert interaction.channel_id is not None
            await self.intake_cog.logic.approve_intake(
                interaction.channel_id, interaction.user.id, review_comment
            )
            logger.info(
                f"草案（帖子ID: {interaction.channel_id}）"
                "已成功批准并进入支持票收集阶段。"
            )
            await interaction.followup.send("✅ 草案已批准，审核信息已记录", ephemeral=True)
        except Exception as e:
            logger.error(
                f"处理草案批准事件时出错 (帖子ID: {interaction.channel_id}): {e}",
                exc_info=True,
            )
            await interaction.followup.send(f"❌ 处理批准时出错: {str(e)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_intake_rejected(
        self,
        interaction: discord.Interaction,
        review_comment: str,
    ):
        logger.info(
            f"接收到草案拒绝事件，审核人: {interaction.user.id}, "
            f"审核意见: {review_comment[:50]}..."
        )
        await safeDefer(interaction, ephemeral=True)

        try:
            assert interaction.channel_id is not None
            await self.intake_cog.logic.reject_intake(
                interaction.channel_id, interaction.user.id, review_comment
            )
            logger.info(f"草案（帖子ID: {interaction.channel_id}）已成功标记为“已拒绝”。")
            await interaction.followup.send("✅ 草案已拒绝，审核信息已记录", ephemeral=True)
        except Exception as e:
            logger.error(
                f"处理草案拒绝事件时出错 (帖子ID: {interaction.channel_id}): {e}",
                exc_info=True,
            )
            await interaction.followup.send(f"❌ 处理拒绝时出错: {str(e)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_intake_modification_requested(
        self,
        interaction: discord.Interaction,
        review_comment: str,
    ):
        logger.info(
            f"接收到草案要求修改事件，审核人: {interaction.user.id}, "
            f"审核意见: {review_comment[:50]}..."
        )
        await safeDefer(interaction, ephemeral=True)

        try:
            assert interaction.channel_id is not None
            await self.intake_cog.logic.request_modification_intake(
                interaction.channel_id, interaction.user.id, review_comment
            )
            logger.info(f"草案（帖子ID: {interaction.channel_id}）已成功标记为“需要修改”。")
            await interaction.followup.send("✅ 已要求修改草案，审核信息已记录", ephemeral=True)
        except Exception as e:
            logger.error(
                f"处理草案要求修改事件时出错 (帖子ID: {interaction.channel_id}): {e}",
                exc_info=True,
            )
            await interaction.followup.send(f"❌ 处理要求修改时出错: {str(e)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_intake_support_vote_added(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        try:
            await self.intake_cog.logic.process_support_toggle(interaction)
        except Exception as e:
            logger.error(f"处理支持票切换时出错: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 操作失败: {str(e)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_intake_edited(
        self,
        interaction: discord.Interaction,
        intake_id: int,
        dto: IntakeSubmissionDto,
    ):
        logger.info(f"接收到草案修改事件，修改人: {interaction.user.id}, 草案ID: {intake_id}")
        await safeDefer(interaction, ephemeral=True)

        try:
            await self.intake_cog.logic.edit_intake(intake_id, dto)
            logger.info(f"✅ 草案 (ID: {intake_id}) 已被成功修改并更新帖子内容。")
            await interaction.followup.send(
                "✅ 提案修改成功！审核帖子内容已更新。",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"处理草案修改事件时出错 (ID: {intake_id}): {e}", exc_info=True)
            await interaction.followup.send(f"❌ 修改提案时出错: {str(e)}", ephemeral=True)
