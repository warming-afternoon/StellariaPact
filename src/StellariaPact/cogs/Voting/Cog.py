import logging
import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from ...share.DiscordUtils import send_private_panel
from ...share.SafeDefer import safeDefer
from ...share.StringUtils import StringUtils
from .dto.VoteDetailDto import VoteDetailDto
from .dto.VoteSessionDto import VoteSessionDto
from .dto.VoteStatusDto import VoteStatusDto
from .qo.DeleteVoteQo import DeleteVoteQo
from .qo.RecordVoteQo import RecordVoteQo
from .views.ObjectionFormalVoteChoiceView import ObjectionFormalVoteChoiceView
from .views.ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder
from .views.VoteEmbedBuilder import VoteEmbedBuilder
from .VotingLogic import VotingLogic

logger = logging.getLogger(__name__)


class Voting(commands.Cog):
    """
    处理所有与投票相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        这个 Cog 的局部错误处理器。
        """
        original_error = getattr(error, "original", error)

        if isinstance(original_error, MissingRole):
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
            logger.error(f"在 Voting Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系技术员", ephemeral=True
                    ),
                    priority=1,
                )

    @commands.Cog.listener()
    async def on_vote_finished(self, session: "VoteSessionDto", result: "VoteStatusDto"):
        """
        监听通用投票结束事件，并发送最终结果。
        """
        try:
            thread = self.bot.get_channel(session.contextThreadId) or await self.bot.fetch_channel(
                session.contextThreadId
            )
            if not isinstance(thread, discord.Thread):
                logger.warning(f"无法为投票会话 {session.id} 找到有效的帖子。")
                return

            topic = StringUtils.clean_title(thread.name)

            # 构建主结果 Embed
            result_embed = VoteEmbedBuilder.build_vote_result_embed(topic, result)
            all_embeds_to_send = [result_embed]

            # 如果不是匿名投票，则构建并添加投票者名单
            if not result.is_anonymous and result.voters:
                approve_voter_ids = [v.userId for v in result.voters if v.choice == 1]
                reject_voter_ids = [v.userId for v in result.voters if v.choice == 0]

                if approve_voter_ids:
                    approve_embeds = VoteEmbedBuilder.build_voter_list_embeds(
                        title="赞成票投票人",
                        voter_ids=approve_voter_ids,
                        color=discord.Color.green(),
                    )
                    all_embeds_to_send.extend(approve_embeds)

                if reject_voter_ids:
                    reject_embeds = VoteEmbedBuilder.build_voter_list_embeds(
                        title="反对票投票人",
                        voter_ids=reject_voter_ids,
                        color=discord.Color.red(),
                    )
                    all_embeds_to_send.extend(reject_embeds)

            # 准备要@的身份组
            council_role_id = self.bot.config.get("roles", {}).get("councilModerator")
            auditor_role_id = self.bot.config.get("roles", {}).get("executionAuditor")
            mentions = []
            if council_role_id:
                mentions.append(f"<@&{council_role_id}>")
            if auditor_role_id:
                mentions.append(f"<@&{auditor_role_id}>")
            content_to_send = " ".join(mentions)

            # 分批发送所有 Embeds
            # Discord 一次最多发送 10 个 embeds
            for i in range(0, len(all_embeds_to_send), 10):
                chunk = all_embeds_to_send[i : i + 10]
                # 只在第一条消息中添加 content
                if i == 0 and content_to_send:
                    await self.bot.api_scheduler.submit(
                        thread.send(content=content_to_send, embeds=chunk),
                        priority=5,
                    )
                else:
                    await self.bot.api_scheduler.submit(
                        thread.send(embeds=chunk),
                        priority=5,
                    )

        except Exception as e:
            logger.error(
                f"处理 'on_vote_finished' 事件时出错 (会话ID: {session.id}): {e}",
                exc_info=True,
            )

    # -------------------------
    # 异议-正式投票 监听器
    # -------------------------

    async def _update_formal_vote_panels(
        self,
        interaction: discord.Interaction,
        vote_details: VoteDetailDto,
        choice_text: str,
        thread_id: int,
    ):
        """
        在投票动作后，统一更新公开的投票面板和私有的管理面板。
        """
        # 更新私有面板
        if interaction.message and interaction.message.embeds:
            new_embed = interaction.message.embeds[0]
            new_embed.set_field_at(3, name="当前投票", value=choice_text, inline=False)
            await self.bot.api_scheduler.submit(
                interaction.edit_original_response(embed=new_embed), 1
            )

        # 更新公开面板
        try:
            thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(
                thread_id
            )
            if not isinstance(thread, (discord.TextChannel, discord.Thread)):
                logger.warning(f"无法为投票 {vote_details.context_message_id} 找到有效的帖子。")
                return

            public_message = await thread.fetch_message(vote_details.context_message_id)
            if not public_message.embeds:
                return

            original_embed = public_message.embeds[0]
            new_embed = ObjectionVoteEmbedBuilder.update_formal_embed(
                original_embed, vote_details
            )
            await self.bot.api_scheduler.submit(public_message.edit(embed=new_embed), 2)
        except (discord.NotFound, discord.Forbidden):
            logger.warning(
                f"无法获取或编辑帖子 {thread_id} 中的原始投票消息 {vote_details.context_message_id}"
            )
        except Exception as e:
            logger.error(f"更新主投票面板时出错: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_objection_formal_vote_manage(self, interaction: discord.Interaction):
        """
        处理用户在“正式异议投票”中点击“管理投票”按钮的事件。
        """
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

        original_message_id = interaction.message.id
        thread_id = interaction.channel.id

        try:
            panel_data = await self.logic.prepare_voting_choice_data(
                user_id=interaction.user.id,
                thread_id=thread_id,
                message_id=original_message_id,
            )

            embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=interaction.message.jump_url,
                panel_data=panel_data,
                base_title="正式异议投票管理",
                approve_text="✅ 同意异议",
                reject_text="❌ 反对异议",
            )

            choice_view = ObjectionFormalVoteChoiceView(
                is_eligible=panel_data.is_eligible,
                on_agree=lambda i: self.bot.dispatch(
                    "objection_formal_vote_record", i, original_message_id, 1, thread_id
                ),
                on_disagree=lambda i: self.bot.dispatch(
                    "objection_formal_vote_record", i, original_message_id, 0, thread_id
                ),
                on_abstain=lambda i: self.bot.dispatch(
                    "objection_formal_vote_abstain", i, original_message_id, thread_id
                ),
            )
            await send_private_panel(self.bot, interaction, embed=embed, view=choice_view)

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

    @commands.Cog.listener()
    async def on_objection_formal_vote_record(
        self,
        interaction: discord.Interaction,
        original_message_id: int,
        choice: int,
        thread_id: int,
    ):
        """
        处理用户从私有面板发起的投票（同意/反对）动作。
        """
        await safeDefer(interaction)

        try:
            vote_details = await self.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=interaction.user.id,
                    message_id=original_message_id,
                    choice=choice,
                )
            )
            choice_text = "✅ 同意异议" if choice == 1 else "❌ 反对异议"
            await self._update_formal_vote_panels(
                interaction, vote_details, choice_text, thread_id
            )
        except Exception as e:
            logger.error(f"记录投票时出错: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("记录投票时出错。", ephemeral=True)

    @commands.Cog.listener()
    async def on_objection_formal_vote_abstain(
        self, interaction: discord.Interaction, original_message_id: int, thread_id: int
    ):
        """
        处理用户从私有面板发起的弃权动作。
        """
        await safeDefer(interaction)

        try:
            vote_details = await self.logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=interaction.user.id,
                    message_id=original_message_id,
                )
            )
            await self._update_formal_vote_panels(
                interaction, vote_details, "未投票", thread_id
            )
        except Exception as e:
            logger.error(f"弃权时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("弃权时发生错误。", ephemeral=True)