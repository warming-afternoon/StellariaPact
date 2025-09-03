import logging

import discord

from StellariaPact.share.DiscordUtils import send_private_panel

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..dto.VoteDetailDto import VoteDetailDto
from ..dto.VotingChoicePanelDto import VotingChoicePanelDto
from ..EligibilityService import EligibilityService
from ..qo.DeleteVoteQo import DeleteVoteQo
from ..qo.RecordVoteQo import RecordVoteQo
from .ObjectionFormalVoteChoiceView import ObjectionFormalVoteChoiceView
from .ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder
from .VoteEmbedBuilder import VoteEmbedBuilder

logger = logging.getLogger(__name__)


class ObjectionFormalVoteView(discord.ui.View):
    """
    用于“正式异议投票”的公开视图。
    采用“管理投票”模式。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    # -----------------
    # 回调和辅助函数
    # -----------------
    async def _update_public_panel(
        self,
        channel: discord.TextChannel | discord.Thread | discord.VoiceChannel,
        message_id: int,
        vote_details: VoteDetailDto,
    ):
        """根据提供的投票详情更新主投票面板。"""
        try:
            public_message = await channel.fetch_message(message_id)
            if not public_message.embeds:
                return

            original_embed = public_message.embeds[0]
            new_embed = ObjectionVoteEmbedBuilder.update_formal_embed(original_embed, vote_details)
            await self.bot.api_scheduler.submit(public_message.edit(embed=new_embed), 2)
        except (discord.NotFound, discord.Forbidden):
            logger.warning(f"无法获取或编辑原始投票消息 {message_id}")
        except Exception as e:
            logger.error(f"更新主投票面板时出错: {e}", exc_info=True)

    async def _on_vote_callback(
        self,
        inner_interaction: discord.Interaction,
        original_message_id: int,
        choice: int,
    ):
        """处理同意或反对投票的回调"""
        await safeDefer(inner_interaction, ephemeral=True)
        self.bot.dispatch(
            "objection_formal_vote_record",
            inner_interaction,
            original_message_id,
            choice,
        )

    async def _on_abstain_callback(
        self, inner_interaction: discord.Interaction, original_message_id: int
    ):
        """处理弃权投票的回调"""
        await safeDefer(inner_interaction, ephemeral=True)
        self.bot.dispatch(
            "objection_formal_vote_abstain", inner_interaction, original_message_id
        )

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
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("objection_formal_vote_manage", interaction)
