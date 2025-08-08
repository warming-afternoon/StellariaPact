import logging

import discord

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..dto.VoteDetailDto import VoteDetailDto
from ..EligibilityService import EligibilityService
from ..qo.DeleteVoteQo import DeleteVoteQo
from ..qo.RecordVoteQo import RecordVoteQo
from .ObjectionFormalVoteChoiceView import ObjectionFormalVoteChoiceView
from .ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder

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

        if not interaction.channel or not isinstance(
            interaction.channel, (discord.Thread, discord.TextChannel)
        ):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在异议帖子内可用。", ephemeral=True), 1
            )
            return

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True), 1
            )
            return

        # 将原始消息ID存储在局部变量中，以便回调可以捕获它
        original_message_id = interaction.message.id

        try:
            # 本地导入以打破循环依赖
            from typing import cast

            from .. import Voting

            voting_cog = cast(Voting, self.bot.get_cog("Voting"))
            if not voting_cog:
                raise ValueError("投票系统组件未就绪。")

            # -----------------
            # 定义回调和辅助函数
            # -----------------
            async def _update_public_panel(vote_details: VoteDetailDto):
                """根据提供的投票详情更新主投票面板。"""
                # 使用 isinstance 进行更严格的类型检查，以消除 Pylance 警告
                if not isinstance(
                    interaction.channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)
                ):
                    logger.warning(
                        f"Attempted to update public panel in a non-messageable channel type: {type(interaction.channel)}"
                    )
                    return
                try:
                    public_message = await interaction.channel.fetch_message(original_message_id)
                    if not public_message.embeds:
                        return

                    original_embed = public_message.embeds[0]
                    new_embed = ObjectionVoteEmbedBuilder.update_formal_embed(
                        original_embed, vote_details
                    )
                    await self.bot.api_scheduler.submit(
                        public_message.edit(embed=new_embed), 2
                    )
                except (discord.NotFound, discord.Forbidden):
                    logger.warning(f"无法获取或编辑原始投票消息 {original_message_id}")
                except Exception as e:
                    logger.error(f"更新主投票面板时出错: {e}", exc_info=True)

            async def _on_vote_callback(
                inner_interaction: discord.Interaction, choice: int
            ):
                """处理同意或反对投票的回调"""
                await safeDefer(inner_interaction)
                try:
                    vote_details = await voting_cog.logic.record_vote_and_get_details(
                        RecordVoteQo(
                            user_id=inner_interaction.user.id,
                            message_id=original_message_id,
                            choice=choice,
                        )
                    )
                    if inner_interaction.message:
                        new_embed = inner_interaction.message.embeds[0]
                        choice_text = "✅ 同意异议" if choice == 1 else "❌ 反对异议"
                        new_embed.set_field_at(3, name="当前投票", value=choice_text, inline=False)
                        await self.bot.api_scheduler.submit(
                            inner_interaction.edit_original_response(embed=new_embed), 1
                        )
                    await _update_public_panel(vote_details)
                except Exception as e:
                    logger.error(f"记录投票时出错: {e}", exc_info=True)
                    if not inner_interaction.response.is_done():
                        await inner_interaction.followup.send("记录投票时出错。", ephemeral=True)

            async def _on_abstain_callback(inner_interaction: discord.Interaction):
                """处理弃权投票的回调"""
                await safeDefer(inner_interaction)
                try:
                    vote_details = await voting_cog.logic.delete_vote_and_get_details(
                        DeleteVoteQo(
                            user_id=inner_interaction.user.id,
                            message_id=original_message_id,
                        )
                    )
                    if inner_interaction.message:
                        new_embed = inner_interaction.message.embeds[0]
                        new_embed.set_field_at(3, name="当前投票", value="未投票", inline=False)
                        await self.bot.api_scheduler.submit(
                            inner_interaction.edit_original_response(embed=new_embed), 1
                        )
                    await _update_public_panel(vote_details)
                    await inner_interaction.followup.send("您已成功弃权。", ephemeral=True)
                except Exception as e:
                    logger.error(f"弃权时发生错误: {e}", exc_info=True)
                    if not inner_interaction.response.is_done():
                        await inner_interaction.followup.send("弃权时发生错误。", ephemeral=True)

            # -----------------
            # 主逻辑
            # -----------------
            async with UnitOfWork(self.bot.db_handler) as uow:
                vote_session = await uow.voting.get_vote_session_by_context_message_id(
                    original_message_id
                )
                if not vote_session or not vote_session.id:
                    raise ValueError("找不到此投票的会话信息。")

                user_activity = await uow.voting.check_user_eligibility(
                    user_id=interaction.user.id, thread_id=interaction.channel.id
                )
                is_eligible = EligibilityService.is_eligible(user_activity)
                message_count = user_activity.messageCount if user_activity else 0

                user_vote = await uow.voting.get_user_vote_by_session_id(
                    user_id=interaction.user.id, session_id=vote_session.id
                )

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

            choice_view = ObjectionFormalVoteChoiceView(
                is_eligible=is_eligible,
                on_agree=lambda i: _on_vote_callback(i, 1),
                on_disagree=lambda i: _on_vote_callback(i, 0),
                on_abstain=_on_abstain_callback,
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
