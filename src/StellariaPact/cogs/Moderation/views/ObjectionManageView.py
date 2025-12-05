import logging

import discord

from StellariaPact.cogs.Moderation.views.ObjectionActionView import ObjectionActionView
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ObjectionManageView(discord.ui.View):
    """
    持久化视图，用于管理一个待审核的异议。
    """

    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="管理异议",
        style=discord.ButtonStyle.primary,
        custom_id="objection_manage_button",
    )
    async def manage_objection(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理“管理异议”按钮点击事件。
        根据用户身份（发起人、管理员、普通用户）显示不同的操作视图。
        """
        # logger.info(
        #     f"管理异议按钮被用户 {interaction.user.id} 在频道 {interaction.channel_id} 中点击。"
        # )
        await safeDefer(interaction, ephemeral=True)

        if not interaction.channel or not isinstance(
            interaction.channel, (discord.Thread, discord.TextChannel)
        ):
            # logger.warning("交互不在有效的频道或帖子中。")
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在频道或帖子内可用。", ephemeral=True), 1
            )

        if not interaction.message:
            logger.warning("无法从交互中找到原始消息。")
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到原始消息，请重试。", ephemeral=True), 1
            )

        objection_id: int | None = None
        objector_id: int | None = None

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 通过审核帖子ID获取异议
            objection = await uow.objection.get_objection_by_review_thread_id(
                interaction.channel.id
            )

            if not objection:
                logger.warning(f"在频道 {interaction.channel.id} 中未找到关连的异议。")
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到关连的异议。", ephemeral=True), 1
                )

            objection_id = objection.id
            objector_id = objection.objector_id

        assert objection_id is not None, "Objection ID cannot be None"
        assert objector_id is not None, "Objector ID cannot be None"

        # 权限检查
        is_objector = interaction.user.id == objector_id
        is_admin = RoleGuard.hasRoles(interaction, "stewards")

        # 如果都没有权限，则显示无权操作
        if not is_objector and not is_admin:
            embed = discord.Embed(
                title="无操作权限",
                description="您不是此异议的发起人，也不是管理员，无法进行操作。",
                color=discord.Color.red(),
            )
            return await self.bot.api_scheduler.submit(
                interaction.followup.send(embed=embed, ephemeral=True), 1
            )

        # 构建并发送带有相应按钮的操作视图
        action_view = ObjectionActionView(
            bot=self.bot,
            objection_id=objection_id,
            is_objector=is_objector,
            is_admin=is_admin,
            channel_id=interaction.channel.id,
            message_id=interaction.message.id,
        )
        embed = discord.Embed(
            title="异议管理",
            description="请选择您要执行的操作。",
            color=discord.Color.blue(),
        )
        await self.bot.api_scheduler.submit(
            interaction.followup.send(embed=embed, view=action_view, ephemeral=True), 1
        )
