import logging

import discord
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.HandleSupportObjectionResultDto import \
    HandleSupportObjectionResultDto
from StellariaPact.cogs.Moderation.dto.ObjectionVotePanelDto import \
    ObjectionVotePanelDto
from StellariaPact.cogs.Moderation.views.ObjectionCreationVoteView import \
    ObjectionCreationVoteView
from StellariaPact.cogs.Voting.qo.BuildFirstObjectionEmbedQo import \
    BuildFirstObjectionEmbedQo
from StellariaPact.cogs.Voting.views.ObjectionVoteEmbedBuilder import \
    ObjectionVoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share.DiscordUtils import DiscordUtils
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class ModerationEventListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic: VotingLogic = VotingLogic(bot)

    @commands.Cog.listener()
    async def on_create_objection_vote_panel(self, dto: ObjectionVotePanelDto, interaction: discord.Interaction | None = None):
        """监听创建异议投票面板的请求"""
        logger.info(f"Received request to create objection vote panel for objection {dto.objection_id}")
        try:
            # 获取频道
            channel_id_str = self.bot.config.get("channels", {}).get("objection_publicity")
            guild_id_str = self.bot.config.get("guild_id")
            guild = (
                interaction.guild
                if interaction and interaction.guild
                else self.bot.get_guild(int(guild_id_str if guild_id_str else 0))
            )

            if not channel_id_str or not guild:
                raise RuntimeError("Publicity channel or server ID is not configured, or server information cannot be obtained.")
            
            channel = await DiscordUtils.fetch_channel(self.bot, int(channel_id_str))

            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError(f"Objection publicity channel (ID: {channel_id_str}) must be a text channel.")

            # 构建 Embed 和 View
            objector = await self.bot.fetch_user(dto.objector_id)
            
            # 使用自己的 ObjectionVoteEmbedBuilder
            embed_qo = BuildFirstObjectionEmbedQo(
                proposal_title=dto.proposal_title,
                proposal_url=f"https://discord.com/channels/{guild.id}/{dto.proposal_thread_id}",
                objector_id=dto.objector_id,
                objector_display_name=objector.display_name,
                objection_reason=dto.objection_reason,
                required_votes=dto.required_votes
            )
            embed = ObjectionVoteEmbedBuilder.build_first_objection_embed(qo=embed_qo)
            view = ObjectionCreationVoteView(self.bot)
            
            message = await channel.send(embed=embed, view=view)
            
            await self.logic.update_vote_session_message_id(dto.vote_session_id, message.id)

        except Exception as e:
            logger.error(f"Error creating objection vote panel for objection {dto.objection_id}: {e}", exc_info=True)


    @commands.Cog.listener()
    async def on_update_objection_vote_panel(self, message: discord.Message, result_dto: HandleSupportObjectionResultDto):
        """监听更新异议投票面板的请求"""
        logger.info(f"Received request to update objection vote panel for message {message.id}")
        try:
            original_embed = message.embeds[0]
            if not message.guild:
                raise RuntimeError("Message does not have guild information.")
            
            guild_id = message.guild.id

            if result_dto.is_goal_reached:
                # 目标达成，更新Embed为“完成”状态，并禁用按钮
                new_embed = ObjectionVoteEmbedBuilder.create_goal_reached_embed(
                    original_embed, result_dto, guild_id
                )
                # 创建一个新的、禁用了按钮的视图
                disabled_view = ObjectionCreationVoteView(self.bot)
                for item in disabled_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True

                await self.bot.api_scheduler.submit(
                    message.edit(embed=new_embed, view=disabled_view), 2
                )
            else:
                # 目标未达成，只更新支持数
                new_embed = ObjectionVoteEmbedBuilder.update_support_embed(
                    original_embed, result_dto, guild_id
                )
                await self.bot.api_scheduler.submit(message.edit(embed=new_embed), 2)
        except Exception as e:
            logger.error(f"Error updating objection vote panel for message {message.id}: {e}", exc_info=True)

async def setup(bot: StellariaPactBot):
    await bot.add_cog(ModerationEventListener(bot))