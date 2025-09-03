import logging
from typing import TYPE_CHECKING

import discord

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ..qo.BuildObjectionReviewResultEmbedQo import BuildObjectionReviewResultEmbedQo
from .ModerationEmbedBuilder import ModerationEmbedBuilder

if TYPE_CHECKING:
    from ..ModerationLogic import ModerationLogic


logger = logging.getLogger(__name__)


class ObjectionReviewReasonModal(discord.ui.Modal):
    """
    一个模态框，供管理员在批准或驳回异议时填写原因。
    """

    reason_input = discord.ui.TextInput(
        label="审核原因",
        style=discord.TextStyle.paragraph,
        placeholder="请填写您批准或驳回此异议的理由...",
        required=True,
        max_length=4000,
    )

    def __init__(
        self,
        bot: StellariaPactBot,
        objection_id: int,
        is_approve: bool,
        logic: "ModerationLogic",
        channel_id: int,
        message_id: int,
    ):
        self.is_approve = is_approve
        action_text = "批准" if is_approve else "驳回"
        super().__init__(title=f"{action_text}异议")

        self.bot = bot
        self.objection_id = objection_id
        self.logic = logic
        self.channel_id = channel_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)
        reason = self.reason_input.value

        try:
            if self.is_approve:
                result_dto = await self.logic.handle_approve_objection(
                    objection_id=self.objection_id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                )
            else:
                result_dto = await self.logic.handle_reject_objection(
                    objection_id=self.objection_id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                )

            # UI 更新
            if result_dto.success:
                # 确保我们有足够的信息来构建 embed
                if (
                    not result_dto.objection
                    or not result_dto.proposal
                    or not result_dto.moderator_id
                    or not result_dto.reason
                    or result_dto.is_approve is None
                ):
                    # 在访问 id 之前，先断言 objection 不为 None
                    assert result_dto.objection is not None
                    logger.error(f"从 logic 返回的 DTO {result_dto.objection.id} 缺少必要信息。")
                    await interaction.followup.send("处理结果时发生内部错误。", ephemeral=True)
                    return

                # 获取审核帖频道
                channel = await self.bot.fetch_channel(self.channel_id)
                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    logger.warning(f"无法找到频道 {self.channel_id} 或频道类型不正确。")
                    await interaction.followup.send("无法找到审核帖。", ephemeral=True)
                    return

                # 构建公开的 embed
                assert channel.guild is not None, "频道必须在服务器中"
                if result_dto.proposal.discussionThreadId is None:
                    logger.error(f"提案 {result_dto.proposal.id} 缺少 discussionThreadId。")
                    await interaction.followup.send("处理结果时发生内部错误。", ephemeral=True)
                    return

                qo = BuildObjectionReviewResultEmbedQo(
                    guild_id=channel.guild.id,
                    proposal_title=result_dto.proposal.title,
                    proposal_thread_id=result_dto.proposal.discussionThreadId,
                    objector_id=result_dto.objection.objectorId,
                    objection_reason=result_dto.objection.reason,
                    moderator_id=result_dto.moderator_id,
                    review_reason=result_dto.reason,
                    is_approve=result_dto.is_approve,
                )
                review_embed = ModerationEmbedBuilder.build_objection_review_result_embed(qo)

                # 在审核帖中发送公开消息，并 @ 发起人
                content = f"异议审核完成，<@{result_dto.objection.objectorId}>"
                await self.bot.api_scheduler.submit(
                    channel.send(content=content, embed=review_embed), 2
                )

                # 禁用原消息的按钮
                try:
                    original_message = await channel.fetch_message(self.message_id)
                    await self.bot.api_scheduler.submit(original_message.edit(view=None), 2)
                except (discord.NotFound, discord.Forbidden) as e:
                    logger.warning(f"无法编辑消息 {self.message_id} 以移除视图: {e}")

            else:
                # 处理业务逻辑层返回的错误
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(f"操作失败：{result_dto.message}", ephemeral=True),
                    1,
                )

        except Exception as e:
            logger.error(f"审核异议 {self.objection_id} 时发生错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("审核操作时发生未知错误。", ephemeral=True), 1
            )
