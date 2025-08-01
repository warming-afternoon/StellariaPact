from asyncio.log import logger
from typing import Awaitable, Callable

import discord
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.qo.GetVoteDetailsQo import GetVoteDetailsQo
from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.cogs.Voting.views.AdjustTimeModal import AdjustTimeModal
from StellariaPact.cogs.Voting.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.StellariaPactBot import StellariaPactBot


class VotingChoiceView(discord.ui.View):
    """
    提供给合格用户进行投票选择的临时视图。
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        original_message_id: int,
        is_eligible: bool,
        is_vote_active: bool,
    ):
        super().__init__(timeout=900)  # 15分钟后超时
        self.bot: StellariaPactBot = interaction.client  # type: ignore
        self.voting_service: VotingService = self.bot.get_cog("Voting").voting_service  # type: ignore
        self.thread_id = interaction.channel.id  # type: ignore
        self.original_message_id = original_message_id
        self.is_vote_active = is_vote_active

        # 如果用户无资格，或者投票已结束，则禁用投票按钮
        if not is_eligible or not is_vote_active:
            self.approve_button.disabled = True
            self.reject_button.disabled = True
            self.abstain_button.disabled = True

        # Dynamically add admin button if the user has the required roles
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor"):
            self._add_admin_buttons()

    def _add_admin_buttons(self):
        """动态添加管理员按钮"""
        adjust_time_button = discord.ui.Button(
            label="调整时间",
            style=discord.ButtonStyle.primary,
            custom_id="adjust_time",
            row=1,
            disabled=not self.is_vote_active,
        )
        adjust_time_button.callback = self.adjust_time_callback
        self.add_item(adjust_time_button)

        toggle_anonymous_button = discord.ui.Button(
            label="切换匿名",
            style=discord.ButtonStyle.secondary,
            custom_id="toggle_anonymous",
            row=1,
            disabled=not self.is_vote_active,
        )
        toggle_anonymous_button.callback = self.toggle_anonymous_callback
        self.add_item(toggle_anonymous_button)

        toggle_realtime_button = discord.ui.Button(
            label="切换实时",
            style=discord.ButtonStyle.secondary,
            custom_id="toggle_realtime",
            row=1,
            disabled=not self.is_vote_active,
        )
        toggle_realtime_button.callback = self.toggle_realtime_callback
        self.add_item(toggle_realtime_button)

    async def _update_main_vote_panel(
        self,
        session: AsyncSession,
        interaction: discord.Interaction,
        vote_session,
    ):
        """使用最新的 vote_session 数据更新主投票面板"""
        try:
            vote_details = None
            if vote_session.realtimeFlag:
                vote_details = await self.voting_service.get_vote_details(
                    session, GetVoteDetailsQo(thread_id=self.thread_id)
                )

            thread = interaction.channel
            if not thread or not isinstance(thread, discord.Thread):
                logger.warning(f"找不到投票帖 (ID: {self.thread_id})")
                return

            original_message = await thread.fetch_message(vote_session.message_id)
            new_embed = VoteEmbedBuilder.create_main_vote_embed(vote_session, vote_details)
            await self.bot.api_scheduler.submit(original_message.edit(embed=new_embed), priority=2)
        except discord.NotFound:
            logger.warning(f"原始投票消息 (ID: {vote_session.message_id}) 未找到, 跳过更新")
        except Exception as e:
            logger.error(f"更新主投票面板时出错: {e}", exc_info=True)

    async def _update_public_vote_counts(self, vote_details):
        """使用 VoteEmbedBuilder 更新面向公众的投票消息。"""
        if not vote_details.realtime_flag:
            return

        try:
            thread = self.bot.get_channel(self.thread_id) or await self.bot.fetch_channel(
                self.thread_id
            )
            if not thread or not isinstance(thread, discord.Thread):
                return

            original_message = await thread.fetch_message(self.original_message_id)

            new_embed = VoteEmbedBuilder.update_vote_counts_embed(
                original_message.embeds[0], vote_details
            )

            await self.bot.api_scheduler.submit(original_message.edit(embed=new_embed), priority=2)
        except discord.NotFound:
            logger.warning(f"原始投票消息 (ID: {self.original_message_id}) 未找到, 跳过更新")
        except Exception as e:
            logger.error(
                f"更新公共投票消息 (ID: {self.original_message_id}) 时出错: {e}",
                exc_info=True,
            )

    async def _record_vote(self, interaction: discord.Interaction, choice: int):
        try:
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.record_user_vote(
                    session,
                    RecordVoteQo(
                        user_id=interaction.user.id, thread_id=self.thread_id, choice=choice
                    ),
                )
                vote_details = await self.voting_service.get_vote_details(
                    session, GetVoteDetailsQo(thread_id=self.thread_id)
                )

            new_embed = interaction.message.embeds[0]
            new_embed.set_field_at(
                3, name="当前投票", value="✅ 赞成" if choice == 1 else "❌ 反对", inline=False
            )

            await self.bot.api_scheduler.submit(
                interaction.response.edit_message(embed=new_embed, view=self), priority=1
            )
            await self.bot.api_scheduler.submit(
                self._update_public_vote_counts(vote_details), priority=2
            )
        except Exception as e:
            logger.error(f"Error recording vote: {e}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    interaction.response.send_message("记录投票时出错。", ephemeral=True),
                    priority=1,
                )

    @discord.ui.button(label="赞成", style=discord.ButtonStyle.success, row=0)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_vote(interaction, 1)

    @discord.ui.button(label="反对", style=discord.ButtonStyle.danger, row=0)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_vote(interaction, 0)

    @discord.ui.button(label="弃票", style=discord.ButtonStyle.secondary, row=0)
    async def abstain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            async with self.bot.db_handler.get_session() as session:
                deleted = await self.voting_service.delete_user_vote(
                    session, user_id=interaction.user.id, thread_id=self.thread_id
                )

                vote_details = await self.voting_service.get_vote_details(
                    session, GetVoteDetailsQo(thread_id=self.thread_id)
                )

            new_embed = interaction.message.embeds[0]
            new_embed.set_field_at(3, name="当前投票", value="未投票", inline=False)

            # Concurrently update the interaction message and the public message
            await self.bot.api_scheduler.submit(
                interaction.response.edit_message(embed=new_embed, view=self), priority=1
            )
            if not deleted:
                return
            await self.bot.api_scheduler.submit(
                self._update_public_vote_counts(vote_details), priority=2
            )
        except Exception as e:
            logger.error(f"Error abstaining from vote: {e}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    interaction.response.send_message("弃票时发生错误。", ephemeral=True),
                    priority=1,
                )

    async def adjust_time_callback(self, interaction: discord.Interaction):
        """Callback for the dynamically added 'Adjust Time' button."""
        modal = AdjustTimeModal(self.bot, self.voting_service, self.thread_id)
        await interaction.response.send_modal(modal)

    async def _handle_toggle_anonymous(self, interaction: discord.Interaction) -> None:
        """处理切换匿名投票的逻辑"""
        async with self.bot.db_handler.get_session() as session:
            vote_session = await self.voting_service.toggle_anonymous(session, self.thread_id)
            if vote_session:
                await self._update_main_vote_panel(session, interaction, vote_session)
                await session.commit()  # 提交更改

                # 发送公开通知
                embed = VoteEmbedBuilder.create_setting_changed_embed(
                    setting_name="匿名投票",
                    new_status="开启" if vote_session.anonymousFlag else "关闭",
                    changed_by=interaction.user,
                )
                await self.bot.api_scheduler.submit(
                    interaction.channel.send(embed=embed), priority=3
                )

    async def _handle_toggle_realtime(self, interaction: discord.Interaction) -> None:
        """处理切换实时票数显示的逻辑"""
        async with self.bot.db_handler.get_session() as session:
            vote_session = await self.voting_service.toggle_realtime(session, self.thread_id)
            if vote_session:
                await self._update_main_vote_panel(session, interaction, vote_session)
                await session.commit()

                embed = VoteEmbedBuilder.create_setting_changed_embed(
                    setting_name="实时票数",
                    new_status="开启" if vote_session.realtimeFlag else "关闭",
                    changed_by=interaction.user,
                )
                await self.bot.api_scheduler.submit(
                    interaction.channel.send(embed=embed), priority=3
                )

    async def _create_and_send_confirmation(
        self,
        interaction: discord.Interaction,
        action_name: str,
        current_status: bool,
        handler: Callable[[discord.Interaction], Awaitable[None]],
    ):
        """创建并发送一个二次确认消息"""
        title = f"确认切换「{action_name}」状态"
        description = (
            f"当前状态: **{'开启' if current_status else '关闭'}**\n\n你确定要切换此设置吗？"
        )
        embed = VoteEmbedBuilder.create_confirmation_embed(title, description)
        view = ConfirmationView(
            bot=self.bot,
            on_confirm_callback=lambda: handler(interaction),
            original_interaction=interaction,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def toggle_anonymous_callback(self, interaction: discord.Interaction):
        """处理“切换匿名”按钮点击事件，发起二次确认"""
        async with self.bot.db_handler.get_session() as session:
            vote_session = await self.voting_service.get_vote_session_by_thread_id(
                session, self.thread_id
            )
        if not vote_session:
            return await interaction.response.send_message("找不到投票会话。", ephemeral=True)

        await self._create_and_send_confirmation(
            interaction,
            "匿名投票",
            vote_session.anonymousFlag,
            self._handle_toggle_anonymous,
        )

    async def toggle_realtime_callback(self, interaction: discord.Interaction):
        """处理“切换实时”按钮点击事件，发起二次确认"""
        async with self.bot.db_handler.get_session() as session:
            vote_session = await self.voting_service.get_vote_session_by_thread_id(
                session, self.thread_id
            )
        if not vote_session:
            return await interaction.response.send_message("找不到投票会话。", ephemeral=True)

        await self._create_and_send_confirmation(
            interaction,
            "实时票数",
            vote_session.realtimeFlag,
            self._handle_toggle_realtime,
        )
