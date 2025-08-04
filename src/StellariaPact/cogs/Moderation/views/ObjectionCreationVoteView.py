import logging

import discord

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ObjectionCreationVoteView(discord.ui.View):
    """
    用于“异议产生票”的视图。
    """

    def __init__(self, bot: StellariaPactBot, objection_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.objection_id = objection_id
        # 动态设置按钮的 custom_id
        self.support_button.custom_id = f"objection_creation_support:{self.objection_id}"

    @discord.ui.button(label="支持此异议", style=discord.ButtonStyle.success)
    async def support_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        处理用户点击“支持此异议”按钮的事件。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), 1)

        # 类型守卫
        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("出现内部错误：无法找到原始消息。", ephemeral=True), 1
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                # 获取投票会话
                vote_session = await uow.voting.get_vote_session_by_context_message_id(
                    interaction.message.id
                )
                if not vote_session or not vote_session.id:
                    await self.bot.api_scheduler.submit(
                        interaction.followup.send("错误：找不到对应的投票会话。", ephemeral=True), 1
                    )
                    return

                # 检查是否已投过票
                existing_vote = await uow.voting.get_user_vote_by_session_id(
                    user_id=interaction.user.id, session_id=vote_session.id
                )
                if existing_vote:
                    await self.bot.api_scheduler.submit(
                        interaction.followup.send("您已经支持过此异议了。", ephemeral=True), 1
                    )
                    return

                # 记录投票 (choice=1 代表支持)
                await uow.voting.create_vote(
                    session_id=vote_session.id, user_id=interaction.user.id, choice=1
                )
                await uow.commit()

                # 更新UI和计票
                votes_count = await uow.voting.get_vote_count_by_session_id(vote_session.id)
                objection = await uow.moderation.get_objection_by_id(self.objection_id)

                if not objection:
                    await self.bot.api_scheduler.submit(
                        interaction.followup.send(
                            "错误：找不到相关的异议，无法更新票数显示。", ephemeral=True
                        ),
                        1,
                    )
                    return

                original_embed = interaction.message.embeds[0]

                # 查找并更新字段
                field_index = -1
                for i, f in enumerate(original_embed.fields):
                    if f.name and "当前支持" in f.name:
                        field_index = i
                        break

                if field_index != -1:
                    original_embed.set_field_at(
                        field_index,
                        name="当前支持",
                        value=f"{votes_count} / {objection.requiredVotes}",
                        inline=True,
                    )

                # 检查是否达到目标
                if votes_count >= objection.requiredVotes:
                    # 更新状态并分派事件
                    await uow.moderation.update_objection_status(self.objection_id, 2) # 2: 异议投票中
                    proposal = await uow.moderation.get_proposal_by_id(objection.proposalId)
                    if not proposal:
                        # 理论上不应该发生，但作为安全检查
                        logger.error(f"在处理异议 {self.objection_id} 时找不到关联的提案 {objection.proposalId}")
                        return

                    await uow.commit() # 提交状态变更

                    original_embed.color = discord.Color.green()
                    original_embed.title = "异议产生票收集完成"
                    original_embed.description = "此异议已获得足够支持，即将进入正式投票阶段。"
                    button.disabled = True
                    button.label = "已达到目标"
                    
                    # 分派事件，通知Moderation/Cog.py开始正式投票
                    self.bot.dispatch("objection_formal_vote_initiation", objection, proposal)
                else:
                    # 仅当未达到目标时才提交，避免重复提交
                    await uow.commit()

                await self.bot.api_scheduler.submit(
                    interaction.message.edit(embed=original_embed, view=self), 5
                )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("成功支持该异议！", ephemeral=True), 1
                )

                # 如果未达到目标，则不需要提交事务，因为在 if/else 块中已经处理
                # 这样可以避免在达到目标时重复提交
                # await uow.commit()

            except Exception as e:
                logger.error(
                    f"处理异议 {self.objection_id} 的支持投票时出错: {e}", exc_info=True
                )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("处理投票时发生未知错误，请联系技术员。", ephemeral=True),
                    1,
                )