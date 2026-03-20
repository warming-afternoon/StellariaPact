import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import ProposalDto
from StellariaPact.share import (
    MissingRole,
    RoleGuard,
    StellariaPactBot,
    StringUtils,
    UnitOfWork,
    safeDefer,
)

logger = logging.getLogger(__name__)


class Voting(commands.Cog):
    """
    处理所有与投票相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        投票 Cog 的局部错误处理器
        """
        original_error = getattr(error, "original", error)

        if isinstance(original_error, MissingRole):
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
            logger.error(f"在 Voting Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系技术员", ephemeral=True
                    ),
                    priority=1,
                )

    @app_commands.command(
        name="创建新提案投票",
        description="为当前讨论帖创建一个新的提案投票",
    )
    @app_commands.describe(
        duration_hours="投票持续时间（小时），默认72小时",
        anonymous="是否匿名投票，默认是",
        realtime="是否实时显示票数，默认是",
        notify="结束时是否通知议员和监票员，默认是",
        max_choices_per_user="单个用户最多可支持的选项数量，默认无限制(999999)",
        ui_style="投票面板样式: 1=标准样式, 2=简洁样式(仅限普通投票)",
    )
    @app_commands.choices(
        duration_hours=[
            app_commands.Choice(name="24小时", value=24),
            app_commands.Choice(name="48小时", value=48),
            app_commands.Choice(name="72小时", value=72),
            app_commands.Choice(name="96小时", value=96),
            app_commands.Choice(name="168小时(7天)", value=168),
        ],
        ui_style=[
            app_commands.Choice(name="1 - 标准样式", value=1),
            app_commands.Choice(name="2 - 简洁样式", value=2),
        ],
    )
    @app_commands.guild_only()
    @RoleGuard.requireRoles("stewards", "councilModerator", "executionAuditor")
    async def create_new_proposal_vote(
        self,
        interaction: discord.Interaction,
        duration_hours: app_commands.Choice[int] | None = None,
        anonymous: bool = True,
        realtime: bool = True,
        notify: bool = True,
        max_choices_per_user: int = 999999,
        ui_style: app_commands.Choice[int] | None = None,
    ):
        """
        创建一个新的提案投票会话。
        在已有投票的情况下也可创建新的投票会话，旧投票不受影响。
        """
        await safeDefer(interaction, ephemeral=True)

        # 检查是否在讨论帖内
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在讨论帖内使用。"), priority=1
            )
            return

        thread = interaction.channel

        # 确保提案记录存在
        proposal = await self._ensure_proposal_exists(thread)
        if not proposal:
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    "无法找到或创建关联的提案记录，请确保帖子在正确的讨论频道内。"
                ),
                priority=1,
            )
            return

        # 处理默认值
        duration = duration_hours.value if duration_hours else 72
        style = ui_style.value if ui_style else 1

        # 参数校验
        if max_choices_per_user < 1:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("每人最多可支持的选项数量必须大于等于1。"), priority=1
            )
            return

        if style not in (1, 2):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("UI样式必须是1（标准）或2（简洁）。"), priority=1
            )
            return

        try:
            # 派发创建新投票事件
            self.bot.dispatch(
                "vote_session_created",
                proposal_dto=proposal,
                options=[],  # 默认选项
                duration_hours=duration,
                anonymous=anonymous,
                realtime=realtime,
                notify=notify,
                create_in_voting_channel=True,
                notify_creation_role=False,
                thread=thread,
                max_choices_per_user=max_choices_per_user,
                ui_style=style,
            )

            # 发送确认消息
            style_text = "标准样式" if style == 1 else "简洁样式"
            confirm_msg = (
                f"✅ 已开始创建新的提案投票。\n"
                f"- 持续时间: {duration}小时\n"
                f"- 匿名投票: {'是' if anonymous else '否'}\n"
                f"- 实时显示: {'是' if realtime else '否'}\n"
                f"- 结束通知: {'是' if notify else '否'}\n"
                f"- 每人最多支持选项数: {max_choices_per_user if max_choices_per_user < 999999 else '无限制'}\n"
                f"- 面板样式: {style_text}"
            )

            await self.bot.api_scheduler.submit(
                interaction.followup.send(confirm_msg), priority=1
            )

        except Exception as e:
            logger.error(f"创建新提案投票时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"创建投票时发生错误: {str(e)}"), priority=1
            )

    # -------------------------
    # 内部辅助方法
    # -------------------------

    async def _ensure_proposal_exists(self, thread: discord.Thread) -> "ProposalDto | None":
        """
        确保指定帖子关联的提案记录存在，若不存在则尝试自动创建。
        返回 ProposalDto 或 None（如果创建失败）。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(thread.id)
            if proposal:
                return ProposalDto.model_validate(proposal)

            # 检查是否在讨论频道内
            discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
            try:
                discussion_channel_id = int(discussion_channel_id_str) if discussion_channel_id_str else None
            except ValueError:
                discussion_channel_id = None

            if not discussion_channel_id or thread.parent_id != discussion_channel_id:
                return None

            logger.info(f"帖子 {thread.id} 缺失 Proposal，开始尝试自动补全...")

            # 尝试获取 Intake 记录
            intake = await uow.intake.get_intake_by_discussion_thread_id(thread.id)
            if intake:
                content = (
                    f"**提案原因:**\n{intake.reason}\n\n"
                    f"**议案动议:**\n{intake.motion}\n\n"
                    f"**执行方案:**\n{intake.implementation}\n\n"
                    f"**执行人:**\n{intake.executor}"
                )
                proposal = await uow.proposal.create_proposal(
                    thread_id=thread.id,
                    proposer_id=intake.author_id,
                    title=intake.title,
                    content=content
                )
                logger.info(f"根据 Intake (ID: {intake.id}) 为帖子 {thread.id} 补全了 Proposal。")
            else:
                # 回退方案：通过首楼内容解析
                starter_content = await StringUtils.extract_starter_content(thread)
                if not starter_content:
                    return None

                proposer_id = StringUtils.extract_proposer_id_from_content(starter_content)
                if not proposer_id:
                    proposer_id = thread.owner_id

                if proposer_id is None:
                    return None

                clean_title = StringUtils.clean_title(thread.name)
                clean_content = StringUtils.clean_proposal_content(starter_content)

                proposal = await uow.proposal.create_proposal(
                    thread_id=thread.id,
                    proposer_id=proposer_id,
                    title=clean_title,
                    content=clean_content
                )
                logger.info(f"根据首楼解析为帖子 {thread.id} 补全了 Proposal。")

            if proposal:
                await uow.commit()
                return ProposalDto.model_validate(proposal)
            return None
