import asyncio

import discord

from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.views.VotingChoiceView import VotingChoiceView
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork


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

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取用户的投票资格和当前投票状态
            user_activity, user_vote, vote_session = await asyncio.gather(
                uow.voting.check_user_eligibility(
                    user_id=interaction.user.id, thread_id=interaction.channel.id
                ),
                uow.voting.get_user_vote(
                    user_id=interaction.user.id, thread_id=interaction.channel.id
                ),
                uow.voting.get_vote_session_by_thread_id(thread_id=interaction.channel.id),
            )

            message_count = user_activity.messageCount if user_activity else 0
            is_eligible = EligibilityService.is_eligible(user_activity)

            if user_vote is None:
                current_vote_status = "未投票"
            elif user_vote.choice == 1:
                current_vote_status = "✅ 赞成"
            else:
                current_vote_status = "❌ 反对"

            embed = discord.Embed(
                title="投票管理",
                color=discord.Color.green() if is_eligible else discord.Color.red(),
            )
            embed.add_field(name="当前发言数", value=f"{message_count}", inline=True)
            embed.add_field(
                name="要求发言数",
                value=f"≥ {EligibilityService.REQUIRED_MESSAGES}",
                inline=True,
            )
            embed.add_field(
                name="资格状态", value="✅ 合格" if is_eligible else "❌ 不合格", inline=True
            )
            embed.add_field(name="当前投票", value=current_vote_status, inline=False)
            if user_activity and not user_activity.validation:
                embed.description = "注意：您的投票资格已被管理员撤销。"

            is_vote_active = vote_session.status == 1 if vote_session else False
            if not is_vote_active:
                embed.add_field(name="投票状态", value="**已结束**", inline=False)
                embed.color = discord.Color.dark_grey()

            is_admin = RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor","stewards")
            # 如果用户不合格且不是管理员，则只显示状态，不显示任何按钮
            if not is_eligible and not is_admin:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(embed=embed, ephemeral=True), priority=1
                )
                return

            # 对于合格用户或管理员，创建并发送带有相应按钮的视图
            view_to_send = VotingChoiceView(
                interaction,
                interaction.message.id,
                is_eligible=is_eligible,
                is_vote_active=is_vote_active,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(embed=embed, view=view_to_send, ephemeral=True),
                priority=1,
            )
