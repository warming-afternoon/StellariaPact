import asyncio
import logging

import discord

from StellariaPact.share.UnitOfWork import UnitOfWork

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ..qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from ..views.VoteEmbedBuilder import VoteEmbedBuilder

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
                # 直接调用服务层来更新时间
                qo = AdjustVoteTimeQo(
                    thread_id=self.thread_id, hours_to_adjust=hours_to_adjust
                )
                result_dto = await uow.voting.adjust_vote_time(qo)
                old_end_time = result_dto.old_end_time
                new_end_time = result_dto.vote_session.endTime
                context_message_id = result_dto.vote_session.contextMessageId
                await uow.commit()

            if not new_end_time or not context_message_id:
                raise ValueError("调整时间后未能获取到必要信息。")

            # 准备 Discord API 调用
            tasks = []
            if interaction.channel and isinstance(
                interaction.channel, discord.Thread
            ):
                # 准备主面板更新
                try:
                    main_vote_message = await interaction.channel.fetch_message(
                        context_message_id
                    )
                    original_embed = main_vote_message.embeds[0]
                    new_embed = original_embed.copy()

                    # 动态查找并更新截止时间字段
                    time_field_found = False
                    for i, field in enumerate(new_embed.fields):
                        if field.name == "截止时间":
                            new_ts = int(new_end_time.timestamp())
                            new_embed.set_field_at(
                                i,
                                name="截止时间",
                                value=f"<t:{new_ts}:F> (<t:{new_ts}:R>)",
                                inline=field.inline,
                            )
                            time_field_found = True
                            break
                    
                    if not time_field_found:
                        # 如果没有找到，就添加一个新的
                        new_ts = int(new_end_time.timestamp())
                        new_embed.add_field(
                            name="截止时间",
                            value=f"<t:{new_ts}:F> (<t:{new_ts}:R>)",
                            inline=False,
                        )

                    tasks.append(main_vote_message.edit(embed=new_embed))

                except (discord.NotFound, IndexError, ValueError) as e:
                    logger.warning(f"无法更新主投票面板: {e}")

                # 准备公开通知
                notification_embed = VoteEmbedBuilder.create_time_adjustment_embed(
                    operator=interaction.user,
                    hours=hours_to_adjust,
                    old_time=old_end_time,
                    new_time=new_end_time,
                )
                tasks.append(interaction.channel.send(embed=notification_embed))

            # 并行执行所有 Discord API 调用
            if tasks:
                await asyncio.gather(
                    *(
                        self.bot.api_scheduler.submit(task, priority=5)
                        for task in tasks
                    )
                )

        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败：{e}", ephemeral=True), priority=1
            )
