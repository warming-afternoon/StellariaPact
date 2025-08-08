
from typing import cast

import discord

from ....share.auth.RoleGuard import RoleGuard
from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ..Cog import Voting
from ..EligibilityService import EligibilityService
from ..views.VotingChoiceView import VotingChoiceView


class VoteView(discord.ui.View):
    """
    投票面板的视图，包含投票按钮。
    """

    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot

    @discord.ui.button(
        label="管理投票", style=discord.ButtonStyle.primary, custom_id="manage_vote_button"
    )
    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理用户点击“管理投票”按钮的事件。
        对所有用户，都显示一个包含其投票资格和投票选项的统一视图。
        如果用户是管理员，该视图会额外包含管理按钮。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), priority=1)

        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True), priority=1
            )
            return

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True),
                priority=1,
            )
            return

        voting_cog = cast(Voting, self.bot.get_cog("Voting"))
        if not voting_cog:
            await interaction.followup.send("投票系统组件未就绪，请联系管理员。", ephemeral=True)
            return

        try:
            panel_data = await voting_cog.logic.prepare_voting_choice_data(
                user_id=interaction.user.id,
                thread_id=interaction.channel.id,
                message_id=interaction.message.id,
            )

            if panel_data.current_vote_choice is None:
                current_vote_status = "未投票"
            elif panel_data.current_vote_choice == 1:
                current_vote_status = "✅ 赞成"
            else:
                current_vote_status = "❌ 反对"

            embed = discord.Embed(
                title="投票管理",
                color=discord.Color.green()
                if panel_data.is_eligible
                else discord.Color.red(),
            )
            embed.add_field(
                name="当前发言数", value=f"{panel_data.message_count}", inline=True
            )
            embed.add_field(
                name="要求发言数",
                value=f"≥ {EligibilityService.REQUIRED_MESSAGES}",
                inline=True,
            )
            embed.add_field(
                name="资格状态",
                value="✅ 合格" if panel_data.is_eligible else "❌ 不合格",
                inline=True,
            )
            embed.add_field(name="当前投票", value=current_vote_status, inline=False)
            if panel_data.is_validation_revoked:
                embed.description = "注意：您的投票资格已被撤销。"

            if not panel_data.is_vote_active:
                embed.add_field(name="投票状态", value="**已结束**", inline=False)
                embed.color = discord.Color.dark_grey()

            is_admin = RoleGuard.hasRoles(
                interaction, "councilModerator", "executionAuditor", "stewards"
            )
            if not panel_data.is_eligible and not is_admin:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(embed=embed, ephemeral=True), priority=1
                )
                return

            view_to_send = VotingChoiceView(
                interaction,
                interaction.message.id,
                is_eligible=panel_data.is_eligible,
                is_vote_active=panel_data.is_vote_active,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(embed=embed, view=view_to_send, ephemeral=True),
                priority=1,
            )
        except Exception as e:
            await interaction.followup.send(f"处理投票管理面板时出错: {e}", ephemeral=True)
