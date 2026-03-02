from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from StellariaPact.cogs.ThreadManage.dto.UpdateProposalContentDto import UpdateProposalContentDto
from StellariaPact.cogs.ThreadManage.views.EditProposalContentModal import EditProposalContentModal
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.share import UnitOfWork, safeDefer
from StellariaPact.share.auth.RoleGuard import RoleGuard

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class ThreadManageCog(commands.Cog):
    """
    处理帖子管理相关的命令和操作，包括修改提案内容。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot

    @app_commands.command(name="修改提案内容", description="[管理组]修改当前提案帖子内容")
    @RoleGuard.requireRoles("stewards")
    async def edit_proposal_content(self, interaction: Interaction):
        """
        修改当前提案帖子的内容。
        仅允许 stewards 身份组使用，且只能修改由当前 BOT 创建的帖子。
        """
        # 检查当前频道是否为论坛频道帖子
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "❌ 此命令只能在提案讨论帖中使用。", ephemeral=True
            )
            return

        thread = interaction.channel
        thread_id = thread.id

        # 检查该帖子是否为当前 BOT 创建的
        if not self.bot.user or thread.owner_id != self.bot.user.id:
            await interaction.response.send_message(
                "❌ 该帖子不是由本 BOT 创建，无法修改。", ephemeral=True
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取帖子对应的 Proposal
            proposal = await uow.proposal.get_proposal_by_thread_id(thread_id)

            if not proposal:
                await interaction.response.send_message(
                    "❌ 当前帖子不是有效的提案讨论帖。", ephemeral=True
                )
                return

            proposal_id = proposal.id

            # 获取对应的 ProposalIntake（可能不存在）
            intake = await uow.intake.get_intake_by_discussion_thread_id(thread_id)
            intake_dto = ProposalIntakeDto.model_validate(intake) if intake else None

        # 弹出 Modal，传入 proposal_id 和 intake_dto（可能为 None）
        modal = EditProposalContentModal(
            proposal_id=proposal_id,  # type: ignore
            intake=intake_dto,
        )
        await interaction.response.send_modal(modal)

    @commands.Cog.listener()
    async def on_proposal_content_update_requested(
        self, dto: UpdateProposalContentDto, interaction: Interaction
    ):
        """
        监听提案内容更新请求事件，执行实际的更新操作。
        先执行数据库操作，再执行 Discord API 操作。
        """
        await safeDefer(interaction, ephemeral=True)

        try:
            # 执行数据库操作（内部会创建自己的 UnitOfWork）
            old_values, changed_fields = await self._handle_update_within_uow(dto)

            # 执行 Discord API 操作
            thread = self.bot.get_channel(dto.thread_id)
            if not isinstance(thread, discord.Thread):
                raise ValueError(f"无法获取帖子 {dto.thread_id} 信息")

            # 更新帖子名称并保留状态前缀
            # 提取可能存在的状态前缀，如 "[讨论中]", "【已结束】" 等
            import re
            prefix_match = re.match(r"^\s*([\[【].*?[\]】])\s*", thread.name)
            prefix = prefix_match.group(1) + " " if prefix_match else ""

            # 拼接新标题 (Discord 帖子名称限制为最多 100 字符)
            new_thread_name = f"{prefix}{dto.title}"[:100]

            # 如果标题发生实质性变化，则更新帖子属性
            if thread.name != new_thread_name:
                await thread.edit(name=new_thread_name)

            starter_message = await thread.fetch_message(thread.id)
            new_content = f"{dto.format_content()}"
            await starter_message.edit(content=new_content)

            # 发送变更记录（如果有变化）
            if changed_fields:
                await self._send_change_embed(thread, interaction, changed_fields)

            # 所有操作成功
            await interaction.followup.send("✅ 提案内容已成功更新！", ephemeral=True)
            logger.info(f"用户 {interaction.user.id} 更新了提案 {dto.proposal_id} 的内容")

        except discord.NotFound as e:
            logger.warning(f"无法在帖子中找到起始消息: {e}")
            await interaction.followup.send("⚠️ 无法找到帖子起始消息，更新已取消。", ephemeral=True)
        except discord.Forbidden as e:
            logger.error(f"没有权限编辑帖子消息: {e}")
            await interaction.followup.send("⚠️ BOT 没有权限编辑帖子，更新已取消。", ephemeral=True)
        except ValueError as e:
            logger.warning(f"更新提案内容失败: {e}")
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        except Exception as e:
            logger.error(f"更新提案内容时发生错误: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 更新提案内容时发生错误，已取消所有更改。", ephemeral=True
            )

    async def _handle_update_within_uow(
        self,
        dto: UpdateProposalContentDto,
    ) -> tuple[dict[str, str | None], list[tuple[str, str, str]]]:
        """
        处理提案更新逻辑，包括数据库更新和变更检测。
        
        返回: (old_values, changed_fields)
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取提案记录
            proposal = await uow.proposal.get_proposal_by_id(dto.proposal_id)
            if not proposal:
                raise ValueError("找不到对应的提案记录")

            # 获取对应的 ProposalIntake（可能不存在）
            intake = await uow.intake.get_intake_by_discussion_thread_id(dto.thread_id)

            # 记录旧值
            old_values = {
                "标题": proposal.title or "",
                "提案原因": intake.reason if intake else None,
                "议案动议": intake.motion if intake else None,
                "执行方案": intake.implementation if intake else None,
                "议案执行人": intake.executor if intake else None,
            }

            # 更新数据库记录
            proposal.title = dto.title
            proposal.content = dto.format_content()
            uow.session.add(proposal)

            if intake:
                intake.title = dto.title
                intake.reason = dto.reason
                intake.motion = dto.motion
                intake.implementation = dto.implementation
                intake.executor = dto.executor
                uow.session.add(intake)

            # 收集新值
            new_values = {
                "标题": dto.title,
                "提案原因": dto.reason,
                "议案动议": dto.motion,
                "执行方案": dto.implementation,
                "议案执行人": dto.executor,
            }

            # 检测变更字段
            changed_fields = self._detect_changed_fields(old_values, new_values)

            logger.info(f"数据库更新完成：提案 {dto.proposal_id} 的内容已更新")

            return old_values, changed_fields

    def _detect_changed_fields(
        self, old_values: dict[str, str | None], new_values: dict[str, str]
    ) -> list[tuple[str, str, str]]:
        """检测发生变化的字段，返回 (字段名, 旧值, 新值) 列表。"""

        def _normalize(value: str | None) -> str:
            return (value or "").strip()

        changed_fields: list[tuple[str, str, str]] = []
        for field_name, new_value in new_values.items():
            old_value = old_values.get(field_name)
            if old_value is None:
                # 历史数据缺失时不做该字段的前后比较
                continue

            old_text = _normalize(old_value)
            new_text = _normalize(new_value)
            if old_text != new_text:
                changed_fields.append((field_name, old_text or "（空）", new_text or "（空）"))

        return changed_fields

    async def _send_change_embed(
        self,
        thread: discord.Thread,
        interaction: Interaction,
        changed_fields: list[tuple[str, str, str]],
    ) -> None:
        """发送变更记录 embed。"""

        def _truncate(value: str, limit: int = 450) -> str:
            if len(value) <= limit:
                return value
            return f"{value[: limit - 1]}…"

        change_embed = discord.Embed(
            title="✏️ 提案内容变更记录",
            description=f"修改人：{interaction.user.mention}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        for field_name, old_text, new_text in changed_fields:
            change_embed.add_field(
                name="**变更项 - " + field_name+ "**",
                value=(
                    f"> **修改前** :\n{_truncate(old_text)}\n\n"
                    f"> **修改后** :\n{_truncate(new_text)}\n"
                    ),
                inline=False,
            )

        await thread.send(embed=change_embed)


async def setup(bot: "StellariaPactBot"):
    """设置 Cog"""
    await bot.add_cog(ThreadManageCog(bot))
    logger.info("ThreadManageCog 已加载")
