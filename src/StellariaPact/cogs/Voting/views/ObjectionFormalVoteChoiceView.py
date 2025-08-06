import logging
from typing import TYPE_CHECKING

import discord

from ....share.SafeDefer import safeDefer
from ....share.UnitOfWork import UnitOfWork
from ..qo.GetVoteDetailsQo import GetVoteDetailsQo
from ..qo.RecordVoteQo import RecordVoteQo
from .ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ObjectionFormalVoteChoiceView(discord.ui.View):
    """
    用于私密消息中的正式异议投票选择视图。
    """

    def __init__(
        self,
        bot: "StellariaPactBot",
        original_message_id: int,
        is_eligible: bool,
        thread_id: int,
    ):
        super().__init__(timeout=300)  # 临时视图
        self.bot = bot
        self.original_message_id = original_message_id
        self.is_eligible = is_eligible
        self.thread_id = thread_id

        # 根据资格禁用按钮
        if not self.is_eligible:
            self.agree_button.disabled = True
            self.disagree_button.disabled = True
            self.abstain_button.disabled = True

    @discord.ui.button(
        label="同意异议",
        style=discord.ButtonStyle.success,
        custom_id="objection_formal_choice_agree",
    )
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“同意”按钮点击事件"""
        await self._record_vote(interaction, 1)

    @discord.ui.button(
        label="反对异议",
        style=discord.ButtonStyle.danger,
        custom_id="objection_formal_choice_disagree",
    )
    async def disagree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“反对”按钮点击事件"""
        await self._record_vote(interaction, 0)

    @discord.ui.button(
        label="弃权",
        style=discord.ButtonStyle.secondary,
        custom_id="objection_formal_choice_abstain",
    )
    async def abstain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“弃权”按钮点击事件，通过删除投票记录实现"""
        await safeDefer(interaction, ephemeral=True)
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                deleted = await uow.voting.delete_user_vote(
                    user_id=interaction.user.id, thread_id=self.thread_id
                )
                await uow.commit()

            feedback = "已弃权。" if deleted else "您尚未投票。"
            await interaction.followup.send(feedback, ephemeral=True)

            # 只有在确实删除了投票记录时才更新公共面板
            if deleted:
                await self._update_public_panel(interaction)

        except Exception as e:
            logger.error(f"弃权时发生错误: {e}", exc_info=True)
            await interaction.followup.send("弃权时发生错误。", ephemeral=True)

    async def _record_vote(self, interaction: discord.Interaction, choice: int):
        """记录或更新用户的投票选择"""
        await safeDefer(interaction, ephemeral=True)
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.voting.record_user_vote(
                    RecordVoteQo(
                        user_id=interaction.user.id,
                        thread_id=self.thread_id,
                        choice=choice,
                    )
                )
                await uow.commit()

            choice_text = "同意异议" if choice == 1 else "反对异议"
            await interaction.followup.send(f"您已投票：**{choice_text}**", ephemeral=True)
            await self._update_public_panel(interaction)

        except Exception as e:
            logger.error(f"记录投票时出错: {e}", exc_info=True)
            await interaction.followup.send("记录投票时出错。", ephemeral=True)

    async def _update_public_panel(self, interaction: discord.Interaction):
        """获取最新数据并更新主投票面板"""
        if not interaction.channel or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                vote_details = await uow.voting.get_vote_details(
                    GetVoteDetailsQo(thread_id=self.thread_id)
                )

            public_message = await interaction.channel.fetch_message(self.original_message_id)
            if not public_message.embeds:
                return

            original_embed = public_message.embeds[0]
            new_embed = ObjectionVoteEmbedBuilder.update_formal_embed(original_embed, vote_details)

            await self.bot.api_scheduler.submit(public_message.edit(embed=new_embed), 2)

        except (discord.NotFound, discord.Forbidden):
            logger.warning(f"无法获取或编辑原始投票消息 {self.original_message_id}")
        except Exception as e:
            logger.error(f"更新主投票面板时出错: {e}", exc_info=True)
