import discord
from discord import Interaction
from discord.ui import Button, View

from StellariaPact.share.auth.RoleGuard import RoleGuard


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
        """当用户点击"填写表单"按钮时，派发打开表单事件。"""
        if not RoleGuard.hasRoles(interaction, "communityBuilder"):
            await interaction.response.send_message(
                "抱歉，你没有提交草案的权限。\n需要'社区建设者'身份", ephemeral=True
            )
            return

        interaction.client.dispatch("intake_submission_requested", interaction)
