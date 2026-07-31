from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

import discord

from StellariaPact.dto import ObjectionSelectionDto
from StellariaPact.share.enums import ObjectionResolutionType

if TYPE_CHECKING:
    from StellariaPact.cogs.Moderation.Cog import Moderation


class ObjectionRemovalModal(discord.ui.Modal):
    """选择要关闭的异议并收集处理分类。"""

    def __init__(
        self,
        cog: "Moderation",
        options: Sequence[ObjectionSelectionDto],
    ):
        super().__init__(title="提案组移除异议", timeout=1000)
        self.cog = cog

        select_options = [
            discord.SelectOption(
                label=f"异议 {option.choice_index}: {option.choice_text}"[:100],
                value=str(option.id),
                description=f"异议记录 ID: {option.id}"[:100],
            )
            for option in options
            if option.id is not None
        ]
        self.objection_select = discord.ui.Select(
            placeholder="请选择一条或多条进行中的异议",
            min_values=1,
            max_values=len(select_options),
            options=select_options,
            required=True,
        )
        self.add_item(
            discord.ui.Label(
                text="要移除的异议（可多选）",
                description="仅显示当前帖子最新的 25 条进行中异议",
                component=self.objection_select,
            )
        )

        self.resolution_select = discord.ui.Select(
            placeholder="请选择处理类型",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="正常流程",
                    value=str(int(ObjectionResolutionType.NORMAL)),
                ),
                discord.SelectOption(
                    label="恶意违规",
                    value=str(int(ObjectionResolutionType.MALICIOUS)),
                    default=True,
                ),
            ],
            required=True,
        )
        self.add_item(
            discord.ui.Label(
                text="类型",
                component=self.resolution_select,
            )
        )

        self.description_input = discord.ui.TextInput(
            label="描述（可选）",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="补充说明本次异议处理原因……",
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        description = self.description_input.value.strip() or None
        await self.cog._initiate_objection_removal_confirmation(
            interaction=interaction,
            option_ids=[int(value) for value in self.objection_select.values],
            resolution_type=int(self.resolution_select.values[0]),
            description=description,
        )
