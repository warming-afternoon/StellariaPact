from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import Modal, TextInput

from StellariaPact.share.enums.LogOperationType import LogOperationType
from StellariaPact.share.UnitOfWork import UnitOfWork

if TYPE_CHECKING:
    from StellariaPact.models.ProposalIntake import ProposalIntake
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeEditReviewModal(Modal):
    """修改审核意见的 Modal —— 任何管理组成员都能修改草案的审核意见。"""

    def __init__(self, bot: "StellariaPactBot", intake: "ProposalIntake"):
        super().__init__(title="修改审核意见")
        self.bot = bot
        self.intake = intake

        current_comment = intake.review_comment or ""

        self.comment_input = TextInput(
            label="审核意见",
            style=discord.TextStyle.paragraph,
            placeholder="请填写修改后的审核意见...",
            default=current_comment,
            required=True,
            max_length=2000,
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id or 0
        new_comment = self.comment_input.value

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                intake_to_update = await uow.intake.get_intake_by_id(
                    self.intake.id, for_update=True,
                )
                if not intake_to_update:
                    await interaction.followup.send("❌ 找不到对应草案。", ephemeral=True)
                    return

                old_comment = intake_to_update.review_comment

                intake_to_update.review_comment = new_comment
                await uow.intake.update_intake(intake_to_update)

                # 写入操作日志
                await uow.operation_log.log_operation(
                    operator_id=interaction.user.id,
                    operator_name=interaction.user.name,
                    operator_display_name=interaction.user.display_name or interaction.user.name,
                    op_type=LogOperationType.INTAKE,
                    action="edit_review_comment",
                    target_type="intake",
                    target_id=self.intake.id or 0,
                    guild_id=guild_id,
                    detail=(
                        f"原意见: {old_comment[:100] if old_comment else '（无）'}, "
                        f"新意见: {new_comment[:100]}"
                    ),
                )

                await uow.commit()

            await interaction.followup.send("✅ 已更新审核意见。", ephemeral=True)
            logger.info(
                f"用户 {interaction.user.id} 修改了草案 {self.intake.id} 的审核意见"
            )

        except Exception as e:
            logger.error(f"修改审核意见时出错: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ 修改审核意见时发生错误: {str(e)}", ephemeral=True
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"修改审核意见 Modal 发生错误 {interaction.user.id}: {error}")
        await interaction.response.defer(ephemeral=True) if not interaction.response.is_done() else None
        error_msg = f"处理修改审核意见时发生错误，请稍后再试。\n{error}"
        await interaction.followup.send(error_msg, ephemeral=True)
