import logging

import discord

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ObjectionFormalVoteView(discord.ui.View):
    """
    用于“正式异议投票”的视图。
    """

    def __init__(self, bot: StellariaPactBot, objection_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.objection_id = objection_id
        # 动态设置按钮的 custom_id
        self.support_button.custom_id = f"objection_formal_support:{self.objection_id}"
        self.reject_button.custom_id = f"objection_formal_reject:{self.objection_id}"
        self.abstain_button.custom_id = f"objection_formal_abstain:{self.objection_id}"

    async def _handle_vote(self, interaction: discord.Interaction, choice: int, choice_text: str):
        """
        处理投票的通用逻辑。
        choice: 1=支持, 2=反对, 3=弃权
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), 1)

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("出现内部错误：无法找到原始消息。", ephemeral=True), 1
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            try:
                vote_session = await uow.voting.get_vote_session_by_context_message_id(
                    interaction.message.id
                )
                if not vote_session or not vote_session.id:
                    await self.bot.api_scheduler.submit(
                        interaction.followup.send("错误：找不到对应的投票会话。", ephemeral=True), 1
                    )
                    return

                existing_vote = await uow.voting.get_user_vote_by_session_id(
                    user_id=interaction.user.id, session_id=vote_session.id
                )
                if existing_vote:
                    # 如果用户已经投过票，但选择了不同的选项，则更新投票
                    if existing_vote.choice != choice:
                        await uow.voting.update_vote(existing_vote.id, choice)
                        await uow.commit()
                        await self.bot.api_scheduler.submit(
                            interaction.followup.send(f"您的投票已从其他选项更改为“{choice_text}”。", ephemeral=True), 1
                        )
                    else:
                        await self.bot.api_scheduler.submit(
                            interaction.followup.send(f"您已经投过“{choice_text}”了。", ephemeral=True), 1
                        )
                    return

                # 记录新投票
                await uow.voting.create_vote(
                    session_id=vote_session.id, user_id=interaction.user.id, choice=choice
                )
                await uow.commit()

                # 更新UI计票 (这部分逻辑可以后续添加，或者通过一个独立的定时任务来完成)
                # ...

                await self.bot.api_scheduler.submit(
                    interaction.followup.send(f"成功投出“{choice_text}”票！", ephemeral=True), 1
                )

            except Exception as e:
                logger.error(
                    f"处理异议 {self.objection_id} 的正式投票时出错: {e}", exc_info=True
                )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("处理投票时发生未知错误，请联系技术员。", ephemeral=True),
                    1,
                )

    @discord.ui.button(label="同意", style=discord.ButtonStyle.success)
    async def support_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_vote(interaction, 1, "同意")

    @discord.ui.button(label="反对", style=discord.ButtonStyle.danger)
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_vote(interaction, 2, "反对")

    @discord.ui.button(label="弃权", style=discord.ButtonStyle.secondary)
    async def abstain_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_vote(interaction, 3, "弃权")