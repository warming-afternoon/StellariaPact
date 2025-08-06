import logging

import discord

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..EligibilityService import EligibilityService
from .ObjectionFormalVoteChoiceView import ObjectionFormalVoteChoiceView

logger = logging.getLogger(__name__)


class ObjectionFormalVoteView(discord.ui.View):
    """
    用于“正式异议投票”的公开视图。
    采用“管理投票”模式。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="管理投票",
        style=discord.ButtonStyle.primary,
        custom_id="objection_formal_manage_vote",
    )
    async def manage_vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        处理用户点击“管理投票”按钮的事件。
        将弹出一个临时的、仅用户可见的视图，其中包含投票资格和投票选项。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在异议帖子内可用。", ephemeral=True), 1
            )
            return

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True), 1
            )
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 1. 获取投票会话信息
                vote_session = await uow.voting.get_vote_session_by_context_message_id(
                    interaction.message.id
                )
                if not vote_session or not vote_session.id:
                    raise ValueError("找不到此投票的会话信息。")

                # 2. 检查用户在异议帖中的发言数以确定资格
                user_activity = await uow.voting.check_user_eligibility(
                    user_id=interaction.user.id, thread_id=interaction.channel.id
                )
                is_eligible = EligibilityService.is_eligible(user_activity)
                message_count = user_activity.messageCount if user_activity else 0

                # 3. 检查用户当前是否已投票
                user_vote = await uow.voting.get_user_vote_by_session_id(
                    user_id=interaction.user.id, session_id=vote_session.id
                )

            # 4. 构建临时Embed
            if user_vote is None:
                current_vote_status = "未投票"
            elif user_vote.choice == 1:
                current_vote_status = "✅ 同意异议"
            else:
                current_vote_status = "❌ 反对异议"

            embed = discord.Embed(
                title="正式异议投票管理",
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

            # 5. 创建并发送带有选择按钮的临时视图
            choice_view = ObjectionFormalVoteChoiceView(
                bot=self.bot,
                original_message_id=interaction.message.id,
                is_eligible=is_eligible,
                thread_id=interaction.channel.id,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(embed=embed, view=choice_view, ephemeral=True), 1
            )

        except ValueError as e:
            logger.warning(f"处理正式异议管理投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"发生错误: {e}", ephemeral=True), 1
            )
        except Exception as e:
            logger.error(f"处理正式异议管理投票时发生未知错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )
