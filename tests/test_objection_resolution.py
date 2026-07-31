import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import discord
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.views.MaliciousObjectionHistoryModal import (
    MaliciousObjectionHistoryModal,
)
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import (
    ModerationEmbedBuilder,
)
from StellariaPact.cogs.Moderation.views.ObjectionRemovalModal import (
    ObjectionRemovalModal,
)
from StellariaPact.dto import ObjectionSelectionDto, ObjectionViolationRecordDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.repository.VoteOptionRepository import VoteOptionRepository
from StellariaPact.share.enums import (
    ConfirmationStatus,
    ObjectionResolutionType,
    ProposalStatus,
    VoteOptionStatus,
)


class _TestDatabaseHandler:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    def get_session(self) -> AsyncSession:
        return AsyncSession(self.engine)


class ObjectionResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        self.bot = SimpleNamespace(
            db_handler=_TestDatabaseHandler(self.engine),
            config={
                "roles": {
                    "councilModerator": "101",
                    "executionAuditor": "102",
                }
            },
            dispatch=Mock(),
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_proposal(
        self,
        *,
        thread_id: int = 100,
        guild_id: int = 1,
        objection_count: int = 2,
    ) -> tuple[int, int, list[int]]:
        async with AsyncSession(self.engine) as session:
            proposal = Proposal(
                discussion_thread_id=thread_id,
                title="分类测试提案",
                content="内容",
                proposer_id=10,
                status=ProposalStatus.UNDER_OBJECTION,
            )
            session.add(proposal)
            await session.flush()
            vote_session = VoteSession(
                guild_id=guild_id,
                context_thread_id=thread_id,
                context_message_id=thread_id + 1000,
                proposal_id=proposal.id,
                total_choices=objection_count,
                status=1,
            )
            session.add(vote_session)
            await session.flush()

            option_ids = []
            for index in range(objection_count):
                option = VoteOption(
                    session_id=vote_session.id,  # type: ignore[arg-type]
                    option_type=1,
                    choice_index=index + 1,
                    choice_text=f"异议 {index + 1}",
                    creator_id=20,
                    creator_name="测试用户",
                    created_at=datetime.now(timezone.utc) - timedelta(hours=2),
                )
                session.add(option)
                await session.flush()
                option_ids.append(option.id)

            session.add(
                UserVote(
                    session_id=vote_session.id,  # type: ignore[arg-type]
                    user_id=30,
                    option_type=1,
                    choice_index=1,
                    choice=0,
                )
            )
            proposal_id = proposal.id
            vote_session_id = vote_session.id
            await session.commit()
            assert proposal_id is not None
            assert vote_session_id is not None
            assert all(option_id is not None for option_id in option_ids)
            return proposal_id, vote_session_id, option_ids  # type: ignore[return-value]

    async def test_selected_removal_preserves_closed_metadata_and_restores_discussion(
        self,
    ) -> None:
        proposal_id, vote_session_id, option_ids = await self._seed_proposal()
        logic = ModerationLogic(self.bot)  # type: ignore[arg-type]

        proposal, restored = await logic.execute_objection_removal(
            proposal_id=proposal_id,
            option_ids=[option_ids[0]],
            resolution_type=ObjectionResolutionType.MALICIOUS,
            resolution_description="刷屏式恶意异议",
        )
        self.assertIsNotNone(proposal)
        self.assertFalse(restored)
        self.assertEqual(proposal.status, ProposalStatus.UNDER_OBJECTION)  # type: ignore[union-attr]

        proposal, restored = await logic.execute_objection_removal(
            proposal_id=proposal_id,
            option_ids=option_ids,
            resolution_type=ObjectionResolutionType.NORMAL,
            resolution_description="正常结束",
        )
        self.assertTrue(restored)
        self.assertEqual(proposal.status, ProposalStatus.DISCUSSION)  # type: ignore[union-attr]

        async with AsyncSession(self.engine) as session:
            options = (
                await session.exec(
                    select(VoteOption)
                    .where(VoteOption.session_id == vote_session_id)
                    .order_by(VoteOption.choice_index)  # type: ignore
                )
            ).all()
            self.assertEqual(options[0].resolution_type, ObjectionResolutionType.MALICIOUS)
            self.assertEqual(options[0].resolution_description, "刷屏式恶意异议")
            self.assertEqual(options[1].resolution_type, ObjectionResolutionType.NORMAL)
            self.assertEqual(options[1].resolution_description, "正常结束")
            self.assertTrue(
                all(option.voting_status == VoteOptionStatus.CLOSED for option in options)
            )
            votes = (
                await session.exec(
                    select(UserVote).where(UserVote.session_id == vote_session_id)
                )
            ).all()
            self.assertEqual(len(votes), 1)

    async def test_malicious_rediscuss_bypasses_blocker_and_persists_payload(self) -> None:
        await self._seed_proposal(objection_count=1)
        async with AsyncSession(self.engine) as session:
            option = (await session.exec(select(VoteOption))).one()
            option.created_at = datetime.now(timezone.utc)
            session.add(option)
            await session.commit()

        logic = ModerationLogic(self.bot)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "未满 1 小时"):
            await logic.handle_rediscuss_proposal(
                channel_id=100,
                guild_id=1,
                user_id=40,
                user_role_ids={101},
                resolution_type=ObjectionResolutionType.NORMAL,
            )

        result = await logic.handle_rediscuss_proposal(
            channel_id=100,
            guild_id=1,
            user_id=40,
            user_role_ids={101},
            resolution_type=ObjectionResolutionType.MALICIOUS,
            description="恶意违规",
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result.session_dto.payload,  # type: ignore[union-attr]
            {"resolution_type": int(ObjectionResolutionType.MALICIOUS)},
        )
        self.assertEqual(result.session_dto.reason, "恶意违规")  # type: ignore[union-attr]

    async def test_normal_multi_remove_rejects_entire_selection_and_malicious_bypasses(
        self,
    ) -> None:
        _, _, option_ids = await self._seed_proposal()
        async with AsyncSession(self.engine) as session:
            blocked_option = await session.get(VoteOption, option_ids[1])
            assert blocked_option is not None
            blocked_option.created_at = datetime.now(timezone.utc)
            session.add(blocked_option)
            await session.commit()

        logic = ModerationLogic(self.bot)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "未满 1 小时"):
            await logic.handle_remove_objections(
                channel_id=100,
                guild_id=1,
                user_id=40,
                user_role_ids={101},
                option_ids=option_ids,
                resolution_type=ObjectionResolutionType.NORMAL,
                description=None,
            )

        result = await logic.handle_remove_objections(
            channel_id=100,
            guild_id=1,
            user_id=40,
            user_role_ids={101},
            option_ids=option_ids,
            resolution_type=ObjectionResolutionType.MALICIOUS,
            description="恶意违规",
        )
        self.assertIsNotNone(result)
        payload = result.session_dto.payload  # type: ignore[union-attr]
        self.assertEqual(payload["resolution_type"], 2)  # type: ignore[index]
        self.assertEqual(
            {item["id"] for item in payload["objections"]},  # type: ignore[index,union-attr]
            set(option_ids),
        )

    async def test_malicious_history_is_scoped_counted_and_limited(self) -> None:
        now = datetime.now(timezone.utc)
        async with AsyncSession(self.engine) as session:
            repository = VoteOptionRepository(session)
            for index in range(6):
                vote_session = VoteSession(
                    guild_id=1 if index < 5 else 2,
                    context_thread_id=500 + index,
                    context_message_id=600 + index,
                    total_choices=1,
                    status=1,
                )
                session.add(vote_session)
                await session.flush()
                option = VoteOption(
                    session_id=vote_session.id,  # type: ignore[arg-type]
                    option_type=1,
                    choice_index=1,
                    choice_text=f"违规异议 {index}",
                    creator_id=20,
                    voting_status=VoteOptionStatus.CLOSED,
                    resolution_type=ObjectionResolutionType.MALICIOUS,
                    resolution_description=f"描述 {index}",
                    closed_at=now + timedelta(minutes=index),
                )
                session.add(option)

            # 同服务器内的正常关闭异议不应进入结果。
            normal_session = VoteSession(
                guild_id=1,
                context_thread_id=999,
                context_message_id=1000,
                total_choices=1,
                status=1,
            )
            session.add(normal_session)
            await session.flush()
            session.add(
                VoteOption(
                    session_id=normal_session.id,  # type: ignore[arg-type]
                    option_type=1,
                    choice_index=1,
                    choice_text="正常异议",
                    creator_id=20,
                    voting_status=VoteOptionStatus.CLOSED,
                    resolution_type=ObjectionResolutionType.NORMAL,
                    closed_at=now,
                )
            )
            await session.commit()

            total, records = await repository.get_malicious_objection_summary(
                guild_id=1,
                creator_id=20,
                limit=4,
            )

        self.assertEqual(total, 5)
        self.assertEqual(len(records), 4)
        self.assertEqual(
            [record.choice_text for record in records],
            ["违规异议 4", "违规异议 3", "违规异议 2", "违规异议 1"],
        )

    async def test_latest_active_objections_are_limited_to_25(self) -> None:
        await self._seed_proposal(objection_count=26)
        options = await ModerationLogic(  # type: ignore[arg-type]
            self.bot
        ).get_latest_active_objections(100)
        self.assertEqual(len(options), 25)
        self.assertEqual(options[0].choice_index, 26)
        self.assertEqual(options[-1].choice_index, 2)

    async def test_modals_and_confirmation_embed_show_expected_details(self) -> None:
        _, _, option_ids = await self._seed_proposal()
        async with AsyncSession(self.engine) as session:
            options = (
                await session.exec(
                    select(VoteOption).where(VoteOption.id.in_(option_ids))  # type: ignore
                )
            ).all()

        removal_options = [
            ObjectionSelectionDto(
                id=option.id,  # type: ignore[arg-type]
                choice_index=option.choice_index,
                choice_text=option.choice_text,
                created_at=option.created_at,
            )
            for option in options
        ]
        removal_modal = ObjectionRemovalModal(
            SimpleNamespace(),  # type: ignore[arg-type]
            removal_options,
        )
        self.assertEqual(len(removal_modal.children), 3)
        self.assertFalse(any(option.default for option in removal_modal.objection_select.options))
        selected_resolution = [
            option.value
            for option in removal_modal.resolution_select.options
            if option.default
        ]
        self.assertEqual(
            selected_resolution,
            [str(int(ObjectionResolutionType.MALICIOUS))],
        )

        records = [
            ObjectionViolationRecordDto(
                option_id=index,
                choice_text=f"违规异议 {index}",
                resolution_description=None,
                created_at=datetime.now(timezone.utc),
                closed_at=datetime.now(timezone.utc),
                guild_id=1,
                thread_id=100 + index,
            )
            for index in range(1, 5)
        ]
        target = SimpleNamespace(
            display_name="目标用户",
            name="target",
            mention="<@20>",
        )
        history_modal = MaliciousObjectionHistoryModal(  # type: ignore[arg-type]
            target, 8, records
        )
        self.assertEqual(len(history_modal.children), 5)
        self.assertTrue(
            all(isinstance(item, discord.ui.TextDisplay) for item in history_modal.children)
        )

        embed = ModerationEmbedBuilder.build_confirmation_embed(
            BuildConfirmationEmbedQo(
                context="proposal_objection_removal",
                status=ConfirmationStatus.PENDING,
                canceler_id=None,
                confirmed_parties={"councilModerator": 1},
                required_roles=["councilModerator", "executionAuditor"],
                role_display_names={
                    "councilModerator": "议事督导",
                    "executionAuditor": "执行监理",
                },
                reason="违规说明",
                payload={
                    "resolution_type": 2,
                    "objections": [{"id": 1, "text": "恶意异议"}],
                },
            ),
            SimpleNamespace(),  # type: ignore[arg-type]
        )
        field_values = "\n".join(str(field.value) for field in embed.fields)
        self.assertIn("恶意违规", field_values)
        self.assertNotIn("2 -", field_values)
        self.assertIn("恶意异议", field_values)
        self.assertIn("违规说明", field_values)


if __name__ == "__main__":
    unittest.main()
