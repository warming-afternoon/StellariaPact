import unittest
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord

from StellariaPact.cogs.Voting.listeners.InnerEventListener import InnerEventListener
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.dto.vote_session import OptionResult, VoteDetailDto
from StellariaPact.share import StellariaPactBot


class VotePrivatePanelTests(unittest.TestCase):
    """私信投票管理面板的说明文本渲染测试。"""

    def setUp(self) -> None:
        self.options = [
            OptionResult(
                choice_index=1,
                choice_text="同意",
                approve_votes=63,
                reject_votes=0,
                total_votes=63,
            )
        ]

    def build_embed(self, option_type: int, description: str | None):
        return VoteEmbedBuilder.build_paginated_manage_embed(
            jump_url="https://discord.com/channels/1/2/3",
            option_type=option_type,
            options=self.options,
            realtime_flag=True,
            ui_style=2,
            max_choices_per_user=1,
            description=description,
        )

    def test_normal_vote_displays_description(self) -> None:
        description = (
            "在坚持保护社区反商业化最高原则的前提下，是否同意为满足特定条件的渠道，"
            "在教程分享区开启有限度的分享允许？"
        )

        embed = self.build_embed(option_type=0, description=description)

        self.assertEqual(embed.description, description)

    def test_normal_vote_omits_empty_description(self) -> None:
        for description in (None, ""):
            with self.subTest(description=description):
                embed = self.build_embed(option_type=0, description=description)
                self.assertIsNone(embed.description)

    def test_objection_vote_does_not_display_normal_vote_description(self) -> None:
        embed = self.build_embed(option_type=1, description="普通投票说明")

        self.assertIsNone(embed.description)


class VotePrivatePanelRefreshTests(unittest.IsolatedAsyncioTestCase):
    """私信管理面板刷新链路的说明文本测试。"""

    async def test_refresh_preserves_normal_vote_description(self) -> None:
        description = "普通投票详细说明"
        option = OptionResult(
            choice_index=1,
            choice_text="同意",
            approve_votes=64,
            reject_votes=0,
            total_votes=64,
        )

        async def submit(awaitable: Awaitable[Any], priority: int) -> Any:
            return await awaitable

        bot = cast(
            StellariaPactBot,
            SimpleNamespace(api_scheduler=SimpleNamespace(submit=submit)),
        )
        edit_original_response = AsyncMock()
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                message=object(),
                edit_original_response=edit_original_response,
            ),
        )
        vote_details = VoteDetailDto(
            guild_id=1,
            context_thread_id=2,
            objection_id=None,
            voting_channel_message_id=None,
            is_anonymous=True,
            notify_flag=True,
            end_time=None,
            context_message_id=None,
            status=1,
            total_choices=1,
            options=[option],
            normal_options=[option],
            objection_options=[],
            realtime_flag=True,
            ui_style=2,
            max_choices_per_user=1,
            description=description,
        )
        listener = InnerEventListener(bot)

        await listener._update_private_management_panel(
            interaction=interaction,
            thread_id=2,
            message_id=3,
            vote_details=vote_details,
            option_type=0,
        )

        edit_original_response.assert_awaited_once()
        awaited_call = edit_original_response.await_args
        assert awaited_call is not None
        refreshed_embed = awaited_call.kwargs["embeds"][0]
        self.assertEqual(refreshed_embed.description, description)


if __name__ == "__main__":
    unittest.main()
