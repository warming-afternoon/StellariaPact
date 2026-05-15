from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import discord

from StellariaPact.cogs.Intake.views.IntakeEmbedBuilder import IntakeEmbedBuilder
from StellariaPact.cogs.Intake.views.IntakeReviewView import IntakeReviewView
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.share import DiscordUtils
from StellariaPact.share.UnitOfWork import UnitOfWork
from StellariaPact.share.enums import IntakeStatus, ProposalStatus

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.dto.IntakeSubmissionDto import IntakeSubmissionDto
    from StellariaPact.cogs.Intake.services.IntakeDiscordHelper import IntakeDiscordHelper
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeDraftService:
    """负责草稿缓存、提交上限检查、草案初始创建。"""

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self._draft_cache: dict[int, tuple[float, "IntakeSubmissionDto"]] = {}

    # -------------------------
    # 草稿缓存管理
    # -------------------------

    def save_draft(self, user_id: int, dto: "IntakeSubmissionDto"):
        """保存用户草稿，记录当前时间戳。"""
        self._draft_cache[user_id] = (time.time(), dto)

    def get_draft(self, user_id: int) -> "IntakeSubmissionDto | None":
        """获取用户草稿，超过 30 分钟则自动清除。"""
        if user_id not in self._draft_cache:
            return None

        timestamp, dto = self._draft_cache[user_id]
        if time.time() - timestamp <= 1800:
            return dto

        del self._draft_cache[user_id]
        return None

    def clear_draft(self, user_id: int):
        """成功提交后清除草稿。"""
        self._draft_cache.pop(user_id, None)

    # -------------------------
    # 提交上限检查
    # -------------------------

    async def check_submission_limit(self, guild_id: int) -> tuple[bool, str]:
        """检查当前讨论中或待审核的提案是否达到上限。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 检查待审核草案是否达到 3 个上限
            pending_intakes = await uow.intake.get_all_pending_intakes()
            if len(pending_intakes) >= 3:
                pending_links = "\n".join(
                    f"- https://discord.com/channels/{guild_id}/{intake.review_thread_id}"
                    for intake in pending_intakes if intake.review_thread_id
                )
                return False, (
                    "预审核区待审核的提案已满（达到 3 个上限），暂不允许提交新草案。\n"
                    "请等待管理组处理现有的待审提案后再提交。\n\n"
                    f"当前待审核提案：\n{pending_links}"
                )

            # 讨论中提案数量检查
            discussion_proposals = await uow.proposal.get_proposals_by_status(
                ProposalStatus.DISCUSSION
            )
            if len(discussion_proposals) >= 3:
                discussion_links = "\n".join(
                    f"- https://discord.com/channels/{guild_id}/{proposal.discussion_thread_id}"
                    for proposal in discussion_proposals
                )
                return False, (
                    "当前已有 3 个或更多提案正在讨论中，暂不允许提交新草案。"
                    "请等待现有议案结案。\n\n"
                    f"正在讨论中的提案：\n{discussion_links}"
                )

        return True, ""

    # -------------------------
    # 草案提交流程
    # -------------------------

    async def process_submit_intake(
        self, dto: "IntakeSubmissionDto", discord_helper: "IntakeDiscordHelper"
    ) -> ProposalIntakeDto:
        """草案提交"""
        allowed, message = await self.check_submission_limit(dto.guild_id)
        if not allowed:
            raise PermissionError(message)

        max_retries = 3
        retry_delay = 0.8

        # 创建草案
        created_intake: ProposalIntake | None = None
        intake_dto: ProposalIntakeDto | None = None
        for attempt in range(max_retries):
            try:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    new_intake = ProposalIntake(
                        guild_id=dto.guild_id,
                        author_id=dto.author_id,
                        title=dto.title,
                        reason=dto.reason,
                        motion=dto.motion,
                        implementation=dto.implementation,
                        executor=dto.executor,
                        status=IntakeStatus.PENDING_REVIEW,
                        required_votes=20,
                    )
                    created = await uow.intake.create_intake(new_intake)
                    intake_dto = ProposalIntakeDto.model_validate(created)
                    created_intake = created
                    await uow.commit()
                    break
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(f"草案提交遇到数据库锁，正在重试 ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        if created_intake is None or intake_dto is None:
            raise RuntimeError("草案提交失败：未能创建草案记录。")

        # 创建审核帖
        channels_config = self.bot.config.get("channels", {})
        review_forum_id = channels_config.get("intake_review")
        if not review_forum_id:
            logger.error("配置中未找到 'intake_review' 频道ID。")
            raise ValueError("审核频道未配置。")

        review_forum = await DiscordUtils.fetch_channel(self.bot, review_forum_id)
        if not isinstance(review_forum, discord.ForumChannel):
            logger.error(f"ID为 {review_forum_id} 的频道不是论坛频道。")
            raise TypeError("审核频道类型不正确。")

        content = IntakeEmbedBuilder.build_review_content(intake_dto)
        pending_tag = discord_helper.resolve_forum_tag(
            forum=review_forum,
            raw_tag_id=self.bot.config.get("intake_tags", {}).get("pending_review"),
            tag_key="pending_review",
        )
        applied_tags = [pending_tag] if pending_tag else []
        title_prefix = discord_helper.get_title_prefix_for_status(IntakeStatus.PENDING_REVIEW)
        thread_name = f"{title_prefix} {intake_dto.title}" if title_prefix else intake_dto.title

        thread_with_message = await review_forum.create_thread(
            name=thread_name,
            content=content,
            view=IntakeReviewView(self.bot, intake_dto),
            applied_tags=applied_tags,
        )

        # 回写 review_thread_id
        assert intake_dto.id is not None
        for attempt in range(max_retries):
            try:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    intake = await uow.intake.get_intake_by_id(intake_dto.id, for_update=True)
                    if not intake:
                        raise ValueError(f"草案不存在，ID={intake_dto.id}")
                    intake.review_thread_id = thread_with_message.thread.id
                    await uow.intake.update_intake(intake)
                    intake_dto = ProposalIntakeDto.model_validate(intake)
                    await uow.commit()
                    return intake_dto
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(
                        f"回写审核帖ID遇到数据库锁，正在重试 "
                        f"({attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        raise RuntimeError("草案提交失败：未能回写审核帖子ID。")
