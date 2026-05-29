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
    """修改审核意见的 Modal —— 预填充当前审核意见，允许管理员修改。"""

    def __init__(self, bot: "StellariaPactBot", reviewer_id: int, intake: "ProposalIntake"):
        super().__init__(title="修改审核意见")
        self.bot = bot
        self.reviewer_id = reviewer_id
        self.intake = intake

        # 判断当前用户是一审还是二审的管理
        if intake.reviewer_id == reviewer_id:
            self.is_first_review = True
            current_comment = intake.review_comment or ""
            review_label = "修改第一位管理审核意见"
        elif intake.reviewer_id_2 == reviewer_id:
            self.is_first_review = False
            current_comment = intake.review_comment_2 or ""
            review_label = "修改第二位管理审核意见"
        else:
            self.is_first_review = False
            current_comment = ""
            review_label = "修改审核意见（未匹配到你的审核记录）"

        self.comment_input = TextInput(
            label=review_label,
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

        if not self.is_first_review and self.intake.reviewer_id_2 != self.reviewer_id:
            # 安全校验：既不是一审也不是二审管理
            await interaction.followup.send(
                "❌ 无法找到你的审核记录，无法修改。", ephemeral=True
            )
            return

        new_comment = self.comment_input.value
        action_detail = "first" if self.is_first_review else "second"

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                intake_to_update = await uow.intake.get_intake_by_id(self.intake.id, for_update=True)
                if not intake_to_update:
                    await interaction.followup.send("❌ 找不到对应草案。", ephemeral=True)
                    return

                old_comment = (
                    intake_to_update.review_comment
                    if self.is_first_review
                    else intake_to_update.review_comment_2
                )

                if self.is_first_review:
                    intake_to_update.review_comment = new_comment
                else:
                    intake_to_update.review_comment_2 = new_comment

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
                        f"审核人类型: {action_detail}, "
                        f"原意见: {old_comment[:100] if old_comment else '（无）'}, "
                        f"新意见: {new_comment[:100]}"
                    ),
                )

                await uow.commit()

            position_text = "第一位管理" if self.is_first_review else "第二位管理"
            await interaction.followup.send(
                f"✅ 已更新{position_text}的审核意见。", ephemeral=True
            )
            logger.info(
                f"用户 {interaction.user.id} 修改了草案 {self.intake.id} 的"
                f" {position_text}审核意见"
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
