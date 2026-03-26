from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, View

from StellariaPact.cogs.Intake.views.IntakeEditModal import IntakeEditModal
from StellariaPact.cogs.Intake.views.IntakeReviewModal import IntakeReviewModal
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.enums import IntakeStatus
from StellariaPact.share.UnitOfWork import UnitOfWork

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeReviewView(View):
    """
    一个用于审核草案和提供提案人修改入口的视图。
    """

    def __init__(self, bot: "StellariaPactBot", intakeDto: "ProposalIntakeDto | None" = None):
        super().__init__(timeout=None)
        self.bot = bot

        # 如果没有传入 intake 对象，则添加所有按钮作为默认布局（用于持久视图注册）
        if intakeDto is None:
            # 默认添加所有按钮，排列为 PENDING_REVIEW 状态下的布局
            # 管理员按钮 (第 0 行)
            approve_btn = Button(
                label="✅ 批准",
                style=discord.ButtonStyle.success,
                custom_id="persistent:intake_approve",
                row=0,
            )
            approve_btn.callback = self.approve
            self.add_item(approve_btn)

            reject_btn = Button(
                label="❌ 拒绝",
                style=discord.ButtonStyle.danger,
                custom_id="persistent:intake_reject",
                row=0,
            )
            reject_btn.callback = self.reject
            self.add_item(reject_btn)

            modify_btn = Button(
                label="📝 要求修改",
                style=discord.ButtonStyle.secondary,
                custom_id="persistent:intake_modify",
                row=0,
            )
            modify_btn.callback = self.modify
            self.add_item(modify_btn)

            # 作者按钮 (第 1 行)
            edit_btn = Button(
                label="✏️ 修改提案",
                style=discord.ButtonStyle.primary,
                custom_id="persistent:intake_edit",
                row=1,
            )
            edit_btn.callback = self.edit_proposal
            self.add_item(edit_btn)
            return

        # 如果传入了具体的 intake，则根据状态动态加载和排版按钮
        if intakeDto.status == IntakeStatus.PENDING_REVIEW:
            # 管理员按钮 (第 0 行)
            approve_btn = Button(
                label="✅ 批准",
                style=discord.ButtonStyle.success,
                custom_id="persistent:intake_approve",
                row=0,
            )
            approve_btn.callback = self.approve
            self.add_item(approve_btn)

            reject_btn = Button(
                label="❌ 拒绝",
                style=discord.ButtonStyle.danger,
                custom_id="persistent:intake_reject",
                row=0,
            )
            reject_btn.callback = self.reject
            self.add_item(reject_btn)

            modify_btn = Button(
                label="📝 要求修改",
                style=discord.ButtonStyle.secondary,
                custom_id="persistent:intake_modify",
                row=0,
            )
            modify_btn.callback = self.modify
            self.add_item(modify_btn)

            # 作者按钮 (第 1 行)
            edit_btn = Button(
                label="✏️ 修改提案",
                style=discord.ButtonStyle.primary,
                custom_id="persistent:intake_edit",
                row=1,
            )
            edit_btn.callback = self.edit_proposal
            self.add_item(edit_btn)

        elif intakeDto.status == IntakeStatus.MODIFICATION_REQUIRED:
            # 只有作者按钮，放在第一行
            edit_btn = Button(
                label="✏️ 修改提案",
                style=discord.ButtonStyle.primary,
                custom_id="persistent:intake_edit",
                row=0,
            )
            edit_btn.callback = self.edit_proposal
            self.add_item(edit_btn)

    async def _check_permissions(self, interaction: discord.Interaction) -> bool:
        """检查用户是否有审核权限（stewards身份组）"""
        if not RoleGuard.hasRoles(interaction, "stewards"):
            await interaction.response.send_message(
                "❌ 您没有权限执行此操作，需要 管理组 身份组。", ephemeral=True
            )
            return False
        return True

    async def _handle_review_action(self, interaction: discord.Interaction, action: str):
        """处理审核动作的通用方法"""
        if not await self._check_permissions(interaction):
            return

        modal = IntakeReviewModal(self.bot, action)
        await interaction.response.send_modal(modal)

    async def approve(self, interaction: discord.Interaction):
        await self._handle_review_action(interaction, "approved")

    async def reject(self, interaction: discord.Interaction):
        await self._handle_review_action(interaction, "rejected")

    async def modify(self, interaction: discord.Interaction):
        await self._handle_review_action(interaction, "modification_requested")

    async def edit_proposal(self, interaction: discord.Interaction):
        """处理提案人点击"修改提案"的事件"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            if not interaction.channel_id:
                return await interaction.response.send_message(
                    "❌ 无法获取帖子上下文。", ephemeral=True
                )

            intake = await uow.intake.get_intake_by_review_thread_id(
                interaction.channel_id
            )
            if not intake:
                return await interaction.response.send_message(
                    "❌ 找不到相关草案。", ephemeral=True
                )

            intake_dto = ProposalIntakeDto.model_validate(intake)
            # 身份校验
            if interaction.user.id != intake.author_id:
                return await interaction.response.send_message(
                    "❌ 只有提案人可以修改该提案。", ephemeral=True
                )

            # 状态校验
            if intake.status not in (
                IntakeStatus.PENDING_REVIEW,
                IntakeStatus.MODIFICATION_REQUIRED,
            ):
                return await interaction.response.send_message(
                    "❌ 提案已进入其他阶段，无法继续修改。", ephemeral=True
                )

            modal = IntakeEditModal(self.bot, intake_dto)
            await interaction.response.send_modal(modal)
