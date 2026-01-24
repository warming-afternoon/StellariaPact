from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.UnitOfWork import UnitOfWork

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
    async def on_intake_submitted(self, dto: IntakeSubmissionDto):
        """
        监听从 IntakeModal 提交的数据。
        """
        logger.info(f"接收到草案提交事件，提交人: {dto.author_id}")
        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                intake = await self.intake_cog.logic.submit_intake(uow, dto)
                await uow.commit()
                logger.info(
                    f"✅ 议案草稿 (ID: {intake.id}) by {dto.author_id} 已成功提交至审核通道。"
                )
            except Exception as e:
                logger.error(f"处理来自 {dto.author_id} 的草案提交时出错: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_intake_approved(self, intake_id: int):
        """
        监听草案被批准的事件。
        """
        logger.info(f"接收到草案批准事件，ID: {intake_id}")
        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                await self.intake_cog.logic.approve_intake(uow, intake_id)
                await uow.commit()
                logger.info(f"草案 {intake_id} 已成功批准并进入支持票收集阶段。")
            except Exception as e:
                logger.error(f"处理草案批准事件时出错 (ID: {intake_id}): {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_intake_rejected(self, intake_id: int):
        """
        监听草案被拒绝的事件。
        """
        logger.info(f"接收到草案拒绝事件，ID: {intake_id}")
        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                await self.intake_cog.logic.reject_intake(uow, intake_id)
                await uow.commit()
                logger.info(f"草案 {intake_id} 已成功标记为“已拒绝”。")
            except Exception as e:
                logger.error(f"处理草案拒绝事件时出错 (ID: {intake_id}): {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_intake_modification_requested(self, intake_id: int):
        """
        监听草案被要求修改的事件。
        """
        logger.info(f"接收到草案要求修改事件，ID: {intake_id}")
        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                await self.intake_cog.logic.request_modification_intake(uow, intake_id)
                await uow.commit()
                logger.info(f"草案 {intake_id} 已成功标记为“需要修改”。")
            except Exception as e:
                logger.error(f"处理草案要求修改事件时出错 (ID: {intake_id}): {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_intake_support_vote_added(self, interaction: discord.Interaction, intake_id: int):
        """
        处理用户点击支持按钮的事件
        """
        # 延迟响应，因为数据库和频道操作可能超过3秒
        await safeDefer(interaction, ephemeral=True)

        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                action, count = await self.intake_cog.logic.handle_support_toggle(
                    uow, interaction.user.id, intake_id
                )
                await uow.commit()

                # 根据不同结果给用户反馈
                if action == "supported":
                    msg = f"✅ 收到支持！当前已收集到 **{count}** 张支持票"
                elif action == "withdrawn":
                    msg = f"⎌ 已撤回支持。当前剩余 **{count}** 张支持票"
                elif action == "promoted":
                    msg = f"🎉 收到支持！该草案已达到 **{count}** 票支持，已开启讨论贴"
                elif action == "already_processed":
                    msg = f"👌 阶段已修改，当前总票数为 **{count}** 票"
                else:
                    msg = "操作成功。"

                await interaction.followup.send(msg, ephemeral=True)

            except Exception as e:
                logger.error(f"处理支持票切换时出错: {e}", exc_info=True)
                await interaction.followup.send(f"❌ 操作失败: {str(e)}", ephemeral=True)
