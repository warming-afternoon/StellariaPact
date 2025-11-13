# Moderation/views/VoteOptionsModal.py
from typing import TYPE_CHECKING, Any, List

import discord

from StellariaPact.share.SafeDefer import safeDefer

if TYPE_CHECKING:
    from ....cogs.Moderation.Cog import Moderation
    from ....share.StellariaPactBot import StellariaPactBot


class VoteOptionsModal(discord.ui.Modal, title="设置投票选项"):
    def __init__(
        self,
        bot: "StellariaPactBot",
        moderation_cog: "Moderation",
        original_interaction: discord.Interaction,
        **kwargs: Any,
    ):
        super().__init__()
        self.bot = bot
        self.moderation_cog = moderation_cog
        self.original_interaction = original_interaction
        self.command_args = kwargs  # 存储原始命令参数

        self.option1 = discord.ui.TextInput(
            label="选项 1",
            placeholder="留空则使用默认的赞成/反对单选项",
            required=False,
            max_length=80,
        )
        self.add_item(self.option1)
        self.option2 = discord.ui.TextInput(
            label="选项 2", placeholder="留空则不使用此选项", required=False, max_length=80
        )
        self.add_item(self.option2)
        self.option3 = discord.ui.TextInput(
            label="选项 3", placeholder="留空则不使用此选项", required=False, max_length=80
        )
        self.add_item(self.option3)
        self.option4 = discord.ui.TextInput(
            label="选项 4", placeholder="留空则不使用此选项", required=False, max_length=80
        )
        self.add_item(self.option4)

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction)

        options: List[str] = [
            opt.value.strip()
            for opt in [self.option1, self.option2, self.option3, self.option4]
            if opt.value and opt.value.strip()
        ]

        await self.moderation_cog.process_proposal_and_vote_creation(
            interaction=interaction,
            options=options,
            duration_hours=self.command_args["duration_hours"],
            anonymous=self.command_args["anonymous"],
            realtime=self.command_args["realtime"],
            notify=self.command_args["notify"],
            create_in_voting_channel=self.command_args["create_in_voting_channel"],
            notify_creation_role=self.command_args["notify_creation_role"],
        )
