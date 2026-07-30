from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from StellariaPact.cogs.Intake.services.IntakeDiscordHelper import IntakeDiscordHelper
from StellariaPact.cogs.Intake.views.IntakeSupportView import IntakeSupportView
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.share.enums import IntakeStatus


class _FakeTextChannel:
    def __init__(self) -> None:
        self.message = SimpleNamespace(edit=AsyncMock())

    async def fetch_message(self, message_id: int):
        return self.message


def _make_intake(status: IntakeStatus) -> ProposalIntakeDto:
    return ProposalIntakeDto(
        id=1,
        guild_id=2,
        author_id=3,
        title="测试草案",
        reason="原因",
        motion="动议",
        implementation="方案",
        executor="执行人",
        status=status,
        review_thread_id=4,
        discussion_thread_id=5 if status == IntakeStatus.APPROVED else None,
        voting_message_id=6,
        required_votes=20,
        reviewer_id=None,
        reviewed_at=None,
        review_comment=None,
    )


class IntakeSupportMessageSyncTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = SimpleNamespace(
            config={"channels": {"objection_publicity": 7}}
        )
        self.helper = IntakeDiscordHelper(self.bot)
        self.channel = _FakeTextChannel()

    async def _sync(self, status: IntakeStatus) -> dict:
        with (
            patch(
                "StellariaPact.cogs.Intake.services.IntakeDiscordHelper."
                "DiscordUtils.fetch_channel",
                new=AsyncMock(return_value=self.channel),
            ),
            patch(
                "StellariaPact.cogs.Intake.services.IntakeDiscordHelper."
                "discord.TextChannel",
                _FakeTextChannel,
            ),
        ):
            updated = await self.helper.update_support_message(
                _make_intake(status), current_votes=14
            )

        self.assertTrue(updated)
        return self.channel.message.edit.await_args.kwargs

    async def test_collecting_message_keeps_support_button(self) -> None:
        kwargs = await self._sync(IntakeStatus.SUPPORT_COLLECTING)

        self.assertIsInstance(kwargs["view"], IntakeSupportView)
        self.assertEqual(kwargs["embed"].fields[1].value, "**14** / 20")
        self.assertEqual(kwargs["embed"].fields[2].value, "🟢 支持票收集中")

    async def test_expired_message_removes_button_and_shows_failure(self) -> None:
        kwargs = await self._sync(IntakeStatus.REJECTED)

        self.assertIsNone(kwargs["view"])
        self.assertEqual(kwargs["embed"].fields[1].value, "**14** / 20")
        self.assertEqual(kwargs["embed"].fields[2].value, "❌ 收集失败")

    async def test_approved_message_removes_button_and_links_discussion(self) -> None:
        kwargs = await self._sync(IntakeStatus.APPROVED)

        self.assertIsNone(kwargs["view"])
        self.assertEqual(kwargs["embed"].fields[1].value, "**14** / 20")
        self.assertEqual(kwargs["embed"].fields[2].value, "✅ 已立案")
        self.assertEqual(
            kwargs["embed"].url,
            "https://discord.com/channels/2/5",
        )
