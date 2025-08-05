import logging

import discord

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ObjectionAdminReviewView(discord.ui.View):
    """
    管理员审核异议的视图，包含批准和驳回按钮。
    """

    def __init__(self, bot: StellariaPactBot, objection_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.objection_id = objection_id

    @discord.ui.button(
        label="批准异议", style=discord.ButtonStyle.success, custom_id="objection_review:approve"
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理批准按钮点击事件。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        async with UnitOfWork(self.bot.db_handler) as uow:
            objection = await uow.moderation.get_objection_by_id(self.objection_id)
            if not objection or objection.status != 0:  # 0: 待审核
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("此异议当前无法被批准。", ephemeral=True), 1
                )

            # 更新状态为“异议贴产生票收集中”
            await uow.moderation.update_objection_status(self.objection_id, 1)

            proposal = await uow.moderation.get_proposal_by_id(objection.proposalId)
            if not proposal:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("找不到关联的提案，操作中止。", ephemeral=True), 1
                )

            await uow.commit()

            # 分派事件以启动“异议产生票”
            self.bot.dispatch("objection_vote_initiation", objection, proposal)

        # 禁用所有按钮
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # 更新原始消息
        if interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.message.edit(
                    content=(
                        f"✅ 操作完成：此异议已被 <@{interaction.user.id}> **批准**，"
                        "将在公示频道开启异议产生票。"
                    ),
                    view=self,
                ),
                2,
            )

        logger.info(
            f"异议 {self.objection_id} 已被管理员 {interaction.user.id} 批准，进入异议产生票阶段。"
        )
        await self.bot.api_scheduler.submit(
            interaction.followup.send("操作成功，异议已批准。", ephemeral=True), 1
        )

    @discord.ui.button(
        label="驳回异议", style=discord.ButtonStyle.danger, custom_id="objection_review:reject"
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理驳回按钮点击事件。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        async with UnitOfWork(self.bot.db_handler) as uow:
            objection = await uow.moderation.get_objection_by_id(self.objection_id)
            if not objection or objection.status != 0:  # 0: 待审核
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("此异议当前无法被驳回。", ephemeral=True), 1
                )

            # 更新状态为“已否决”
            await uow.moderation.update_objection_status(self.objection_id, 4)
            await uow.commit()

        # 禁用所有按钮
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # 更新原始消息
        if interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.message.edit(
                    content=f"❌ 操作完成：此异议已被 <@{interaction.user.id}> **驳回**。",
                    view=self,
                ),
                2,
            )

        logger.info(f"异议 {self.objection_id} 已被管理员 {interaction.user.id} 驳回。")
        await self.bot.api_scheduler.submit(
            interaction.followup.send("操作成功，异议已驳回。", ephemeral=True), 1
        )
