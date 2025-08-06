import logging
from typing import TYPE_CHECKING

import discord

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot

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
    ):
        self.is_approve = is_approve
        action_text = "批准" if is_approve else "驳回"
        super().__init__(title=f"{action_text}异议")

        self.bot = bot
        self.objection_id = objection_id
        self.logic = logic

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
                # 断言消息存在，以帮助类型检查器
                assert interaction.message is not None, "操作的原始消息不应为 None"
                view = interaction.message.view  # type: ignore
                if view:
                    # 禁用所有按钮
                    for item in view.children:
                        if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                            item.disabled = True
                    # 更新原始消息
                    await self.bot.api_scheduler.submit(
                        interaction.message.edit(content=result_dto.message, view=view),
                        2,
                    )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("操作成功。", ephemeral=True), 1
                )
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
