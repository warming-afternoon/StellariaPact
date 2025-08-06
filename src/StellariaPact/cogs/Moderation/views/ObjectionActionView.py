import logging

import discord

from StellariaPact.cogs.Moderation.views.EditObjectionReasonModal import (
    EditObjectionReasonModal,
)
from StellariaPact.cogs.Moderation.views.ObjectionReviewReasonModal import (
    ObjectionReviewReasonModal,
)
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class ObjectionActionView(discord.ui.View):
    """
    一个临时的视图，根据用户权限显示不同的异议管理操作按钮。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        objection_id: int,
        is_objector: bool,
        is_admin: bool,
    ):
        super().__init__(timeout=900)  # 15分钟后超时
        self.bot = bot
        self.objection_id = objection_id

        # 根据权限动态添加按钮
        if is_objector:
            self._add_objector_buttons()
        if is_admin:
            self._add_admin_buttons()

    def _add_objector_buttons(self):
        """添加异议发起人专用的按钮"""
        edit_button = discord.ui.Button(
            label="编辑异议内容",
            style=discord.ButtonStyle.primary,
            custom_id="objection_action:edit",
            row=0,
        )
        edit_button.callback = self.edit_objection_callback
        self.add_item(edit_button)

    def _add_admin_buttons(self):
        """添加管理员专用的按钮"""
        approve_button = discord.ui.Button(
            label="批准",
            style=discord.ButtonStyle.success,
            custom_id="objection_action:approve",
            row=1,
        )
        approve_button.callback = self.approve_callback
        self.add_item(approve_button)

        reject_button = discord.ui.Button(
            label="驳回",
            style=discord.ButtonStyle.danger,
            custom_id="objection_action:reject",
            row=1,
        )
        reject_button.callback = self.reject_callback
        self.add_item(reject_button)

    async def edit_objection_callback(self, interaction: discord.Interaction):
        """处理“编辑异议内容”按钮点击"""
        modal = EditObjectionReasonModal(bot=self.bot, objection_id=self.objection_id)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    async def approve_callback(self, interaction: discord.Interaction):
        """处理“批准”按钮点击"""
        logic = self.bot.get_cog("Moderation").logic  # type: ignore
        modal = ObjectionReviewReasonModal(
            bot=self.bot,
            objection_id=self.objection_id,
            is_approve=True,
            logic=logic,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    async def reject_callback(self, interaction: discord.Interaction):
        """处理“驳回”按钮点击"""
        logic = self.bot.get_cog("Moderation").logic  # type: ignore
        modal = ObjectionReviewReasonModal(
            bot=self.bot,
            objection_id=self.objection_id,
            is_approve=False,
            logic=logic,
        )
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
