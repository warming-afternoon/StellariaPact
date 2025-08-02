import asyncio
import logging

import discord

from StellariaPact.cogs.Voting.dto.AdjustVoteTimeDto import AdjustVoteTimeDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.GetVoteDetailsQo import GetVoteDetailsQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class AdjustTimeModal(discord.ui.Modal, title="调整投票时间"):
    """
    一个让管理员输入要调整的小时数的模态框。
    """

    hours = discord.ui.TextInput(
        label="调整的小时数",
        placeholder="输入一个整数，例如 24 (延长一天) 或 -12 (缩短半天)",
        required=True,
    )

    def __init__(self, bot: StellariaPactBot, thread_id: int):
        super().__init__(timeout=1800)
        self.bot = bot
        self.thread_id = thread_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        try:
            hours_to_adjust = int(self.hours.value)
        except ValueError:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("请输入一个有效的整数。", ephemeral=True),
                priority=1,
            )
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 1. 更新数据库
                qo = AdjustVoteTimeQo(thread_id=self.thread_id, hours_to_adjust=hours_to_adjust)
                result_dto: AdjustVoteTimeDto = await uow.voting.adjust_vote_time(qo)
                vote_session = result_dto.vote_session
                old_end_time = result_dto.old_end_time
                new_end_time = vote_session.endTime

            if not new_end_time:
                # This should not happen if the service logic is correct
                raise ValueError("调整时间后未能获取新的结束时间。")

            # 2. 准备更新主投票面板
            tasks = []
            if (
                vote_session.contextMessageId
                and interaction.channel
                and isinstance(interaction.channel, discord.abc.Messageable)
            ):
                try:
                    # 类型检查，确保 channel 是 Thread
                    if not isinstance(interaction.channel, discord.Thread):
                        logger.warning("AdjustTimeModal 只能在帖子中使用。")
                        return

                    # 获取主投票消息
                    main_vote_message = await self.bot.api_scheduler.submit(
                        interaction.channel.fetch_message(vote_session.contextMessageId),
                        priority=3,
                    )

                    # 如果是实时投票，需要获取票数详情
                    vote_details = None
                    if vote_session.realtimeFlag:
                        vote_details = await uow.voting.get_vote_details(
                            GetVoteDetailsQo(thread_id=self.thread_id)
                        )

                    # 使用 VoteEmbedBuilder 重新构建整个 embed
                    updated_embed = VoteEmbedBuilder.create_vote_panel_embed(
                        topic=interaction.channel.name,
                        anonymous_flag=vote_session.anonymousFlag,
                        realtime_flag=vote_session.realtimeFlag,
                        end_time=vote_session.endTime,
                        vote_details=vote_details,
                    )

                    # 添加更新主面板的任务
                    tasks.append(
                        self.bot.api_scheduler.submit(
                            main_vote_message.edit(embed=updated_embed), priority=5
                        )
                    )
                except (discord.NotFound, IndexError) as e:
                    logger.warning(f"无法更新主投票面板: {e}")

            # 3. 准备发送公开通知
            if interaction.channel and isinstance(interaction.channel, discord.abc.Messageable):
                notification_embed = VoteEmbedBuilder.create_time_adjustment_embed(
                    operator=interaction.user,
                    hours=hours_to_adjust,
                    old_time=old_end_time,
                    new_time=new_end_time,
                )
                tasks.append(
                    self.bot.api_scheduler.submit(
                        interaction.channel.send(embed=notification_embed), priority=5
                    )
                )

            # 4. 并行执行所有 Discord API 调用
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败：{e}", ephemeral=True), priority=1
            )
