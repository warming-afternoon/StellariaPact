from asyncio.log import logger

import discord

from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.cogs.Voting.views.VoteAdminView import VoteAdminView
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot


class VotingChoiceView(discord.ui.View):
    """
    提供给合格用户进行投票选择的临时视图。
    """

    def __init__(
        self, bot: StellariaPactBot, voting_service: VotingService, thread_id: int
    ):
        super().__init__(timeout=180)  # 3分钟后超时
        self.bot = bot
        self.voting_service = voting_service
        self.thread_id = thread_id

    async def _record_vote(self, interaction: discord.Interaction, choice: int):
        await self.bot.api_scheduler.submit(
            interaction.response.defer(ephemeral=True), priority=1
        )
        try:
            qo = RecordVoteQo(
                user_id=interaction.user.id,
                thread_id=self.thread_id,
                choice=choice,
            )
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.record_user_vote(session, qo)

            feedback_message = (
                "你的投票（赞成）已成功记录！" if choice == 1 else "你的投票（反对）已成功记录！"
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(feedback_message, ephemeral=True), priority=1
            )

            # 禁用所有按钮
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.edit_original_response(view=self)

        except Exception as e:
            logger.error(f"记录投票时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("记录投票时发生错误，请联系管理员。", ephemeral=True),
                priority=1,
            )
        finally:
            self.stop()

    @discord.ui.button(label="赞成", style=discord.ButtonStyle.success)
    async def approve_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._record_vote(interaction, 1)

    @discord.ui.button(label="反对", style=discord.ButtonStyle.danger)
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._record_vote(interaction, 0)


class VoteView(discord.ui.View):
    """
    投票面板的视图，包含投票按钮。
    """

    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot
        self.voting_service = voting_service

    @discord.ui.button(
        label="管理投票", style=discord.ButtonStyle.primary, custom_id="manage_vote_button"
    )
    async def vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        处理用户点击“管理投票”按钮的事件。
        根据用户权限分发不同的视图。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True),
                priority=1,
            )
            return

        # 检查用户是否为管理员
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor"):
            admin_view = VoteAdminView(
                self.bot, self.voting_service, interaction.channel.id
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    "请选择一项管理操作：", view=admin_view, ephemeral=True
                ),
                priority=1,
            )
        else:
            # 对于普通用户，显示其投票资格状态
            async with self.bot.db_handler.get_session() as session:
                user_activity = await self.voting_service.check_user_eligibility(
                    session,
                    user_id=interaction.user.id,
                    thread_id=interaction.channel.id,
                )

            message_count = user_activity.messageCount if user_activity else 0
            is_valid = user_activity.validation == 1 if user_activity else True
            required_messages = 3  # 投票要求的发言数

            is_eligible = message_count >= required_messages and is_valid

            embed = discord.Embed(
                title="投票资格状态",
                color=discord.Color.green() if is_eligible else discord.Color.red(),
            )
            embed.add_field(
                name="当前发言数", value=f"{message_count}", inline=True
            )
            embed.add_field(
                name="要求发言数", value=f"≥ {required_messages}", inline=True
            )
            embed.add_field(
                name="资格状态",
                value="✅ 合格" if is_eligible else "❌ 不合格",
                inline=False,
            )
            if not is_valid:
                embed.description = "注意：您的投票资格已被管理员撤销。"

            if is_eligible:
                view_to_send = VotingChoiceView(
                    self.bot, self.voting_service, interaction.channel.id
                )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(
                        embed=embed, view=view_to_send, ephemeral=True
                    ),
                    priority=1,
                )
            else:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(embed=embed, ephemeral=True),
                    priority=1,
                )
