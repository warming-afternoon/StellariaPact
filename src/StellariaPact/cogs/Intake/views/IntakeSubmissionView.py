import discord
from discord import Interaction
from discord.ui import Button, View

from StellariaPact.cogs.Intake.IntakeModal import IntakeModal


class IntakeSubmissionView(View):
    """
    一个持久化的视图，包含“填写表单”按钮。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 填写表单",
        style=discord.ButtonStyle.primary,
        custom_id="persistent:submit_intake_form",
    )
    async def submit_button(self, interaction: Interaction, button: Button):
        """当用户点击“填写表单”按钮时，弹出模态框。"""
        modal = IntakeModal()
        await interaction.response.send_modal(modal)
