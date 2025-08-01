import asyncio
import logging

import discord

from StellariaPact.cogs.Voting.dto.AdjustVoteTimeDto import AdjustVoteTimeDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot

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

    def __init__(self, bot: StellariaPactBot, voting_service: VotingService, thread_id: int):
        super().__init__()
        self.bot = bot
        self.voting_service = voting_service
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
            async with self.bot.db_handler.get_session() as session:
                # 1. 更新数据库
                qo = AdjustVoteTimeQo(thread_id=self.thread_id, hours_to_adjust=hours_to_adjust)
                result_dto: AdjustVoteTimeDto = await self.voting_service.adjust_vote_time(
                    session, qo
                )
                vote_session = result_dto.vote_session
                old_end_time = result_dto.old_end_time
                new_end_time = vote_session.endTime

                # 2. 准备更新主投票面板
                tasks = []
                if vote_session.contextMessageId and interaction.channel:
                    try:
                        # 获取主投票消息和其原始 embed
                        main_vote_message = await interaction.channel.fetch_message(
                            vote_session.contextMessageId
                        )
                        original_embed = main_vote_message.embeds[0]

                        # 更新 embed 中的时间字段
                        # 这里我们不能直接修改 embed，而是需要重新构建或精确修改字段
                        # 为了简单起见，我们直接在原始 embed 上修改时间字段
                        # 注意：一个更健壮的方法是 VoteEmbedBuilder 有一个专门更新时间的函数
                        updated_embed = original_embed.copy()
                        for i, field in enumerate(updated_embed.fields):
                            if field.name == "截止时间":
                                updated_embed.set_field_at(
                                    i,
                                    name="截止时间",
                                    value=f"<t:{int(new_end_time.timestamp())}:F>",
                                    inline=False,
                                )
                                break
                        else:  # 如果没有找到截止时间字段，则添加一个新的
                            updated_embed.add_field(
                                name="截止时间",
                                value=f"<t:{int(new_end_time.timestamp())}:F>",
                                inline=False,
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
                if interaction.channel:
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

                pass

        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败：{e}", ephemeral=True), priority=1
            )
