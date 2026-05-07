from __future__ import annotations

from typing import TYPE_CHECKING

from .services.IntakeDiscordHelper import IntakeDiscordHelper
from .services.IntakeDraftService import IntakeDraftService
from .services.IntakeReviewService import IntakeReviewService
from .services.IntakeTransitionService import IntakeTransitionService
from .services.IntakeVoteService import IntakeVoteService

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.dto.IntakeSubmissionDto import IntakeSubmissionDto
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeLogic:
    """
    Intake 逻辑的门面类 (Facade)。
    将各领域的业务逻辑分发给底层的具体 Service 处理。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot

        # 实例化 Discord Helper（纯视图操作，不依赖其他 Service）
        self.discord_helper = IntakeDiscordHelper(bot)

        # 实例化各业务 Service，注入 bot 和必要的依赖
        self.draft_service = IntakeDraftService(bot)
        self.transition_service = IntakeTransitionService(bot, self.discord_helper)
        self.vote_service = IntakeVoteService(bot, self.discord_helper, self.transition_service)
        self.review_service = IntakeReviewService(bot, self.discord_helper)

    # -------------------------
    # 草案管理路由 → IntakeDraftService
    # -------------------------

    def save_draft(self, user_id: int, dto: "IntakeSubmissionDto"):
        """保存用户草稿，记录当前时间戳。"""
        return self.draft_service.save_draft(user_id, dto)

    def get_draft(self, user_id: int):
        """获取用户草稿，超过 30 分钟则自动清除。"""
        return self.draft_service.get_draft(user_id)

    def clear_draft(self, user_id: int):
        """成功提交后清除草稿。"""
        return self.draft_service.clear_draft(user_id)

    async def check_submission_limit(self, guild_id: int):
        """检查当前讨论中的提案是否达到上限。"""
        return await self.draft_service.check_submission_limit(guild_id)

    # -------------------------
    # 草案提交流程路由 → IntakeDraftService
    # -------------------------

    async def process_submit_intake(self, dto: "IntakeSubmissionDto"):
        """草案提交"""
        return await self.draft_service.process_submit_intake(dto, self.discord_helper)

    # -------------------------
    # 审核流程路由 → IntakeReviewService
    # -------------------------

    async def approve_intake(self, thread_id: int, reviewer_id: int, review_comment: str):
        """草案审核 - 通过（双管理审核）。"""
        return await self.review_service.approve_intake(thread_id, reviewer_id, review_comment)

    async def reject_intake(self, thread_id: int, reviewer_id: int, review_comment: str):
        """草案审核 - 拒绝"""
        return await self.review_service.reject_intake(thread_id, reviewer_id, review_comment)

    async def edit_intake(self, intake_id: int, dto):
        """提案人修改草案"""
        return await self.review_service.edit_intake(intake_id, dto)

    async def request_modification_intake(self, thread_id: int, reviewer_id: int, review_comment: str):
        """草案审核 - 需要修改"""
        return await self.review_service.request_modification_intake(thread_id, reviewer_id, review_comment)

    # -------------------------
    # 投票与转段路由 → IntakeVoteService / IntakeTransitionService
    # -------------------------

    async def process_support_toggle(self, interaction):
        """支持票切换总入口"""
        return await self.vote_service.process_support_toggle(interaction)

    async def close_expired_intake(self, intake_id: int):
        """处理因支持票不足而过期的草案。"""
        return await self.vote_service.close_expired_intake(intake_id)

    async def handle_intake_transition_confirmed(self, intake_id: int):
        """转段确认完成后：解锁讨论帖或建立讨论帖（向后兼容）。"""
        return await self.transition_service.handle_intake_transition_confirmed(intake_id)
