import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Punishment.constants import (
    OFF_TOPIC_REASON,
    PERMANENT_THREAD_MUTE,
    chinese_number,
)
from StellariaPact.cogs.Punishment.dto import PunishmentRecordDto
from StellariaPact.cogs.Punishment.listeners.PunishmentListener import PunishmentListener
from StellariaPact.cogs.Punishment.logic.PunishmentLogic import PunishmentLogic
from StellariaPact.cogs.Punishment.qo import (
    ApplyThreadPunishmentQo,
    LiftThreadPunishmentQo,
    QueryThreadPunishmentQo,
)
from StellariaPact.cogs.StructuredSpeech.StructuredSpeechService import StructuredSpeechService
from StellariaPact.models.PunishmentRecord import PunishmentRecord
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.repository.PunishmentRecordRepository import PunishmentRecordRepository
from StellariaPact.repository.UserActivityRepository import UserActivityRepository
from StellariaPact.share.BusinessRuleError import BusinessRuleError


@pytest_asyncio.fixture
async def logic():
    """使用真实 SQLite 事务和共享 Bot，隔离 Discord 网络。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    bot = SimpleNamespace(
        db_handler=SimpleNamespace(get_session=lambda: AsyncSession(engine)), dispatch=MagicMock()
    )
    yield PunishmentLogic(bot)
    await engine.dispose()


async def apply(logic, *, mode="cumulative", thread_id=10, user_id=20, **overrides):
    arguments = dict(
        guild_id=1,
        thread_id=thread_id,
        target_user_id=user_id,
        moderator_id=30,
        reason="人工处罚",
        source_message_url=None,
        voting_allowed=True,
        mute_end_time=None,
        quick_mode=mode,
        off_topic_confirmed=True,
    )
    arguments.update(overrides)
    return await logic.apply_thread_punishment(ApplyThreadPunishmentQo(**arguments))


async def lift(logic, result, *, thread_id=10, user_id=20):
    return await logic.lift_thread_punishment(
        LiftThreadPunishmentQo(
            thread_id=thread_id,
            target_user_id=user_id,
            expected_record_id=result.punishment_record_id,
            moderator_id=30,
            reason="解除测试",
        )
    )


@pytest.mark.asyncio
async def test_cumulative_tiers_scope_and_permanent_restart(logic):
    """验证五档理由、帖子和用户隔离，以及永久禁言的存储及重启拦截。"""
    for ordinal, minutes in enumerate((5, 10, 30, None, None), start=1):
        before = datetime.now(timezone.utc)
        result = await apply(logic)
        after = datetime.now(timezone.utc)
        assert result.cumulative_count == ordinal
        assert result.reason == f"{OFF_TOPIC_REASON}，{chinese_number(ordinal)}次处罚"
        assert result.voting_allowed
        if minutes is None:
            assert result.mute_end_time == PERMANENT_THREAD_MUTE
        else:
            assert before + timedelta(minutes=minutes) <= result.mute_end_time
            assert result.mute_end_time <= after + timedelta(minutes=minutes)
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=10, target_user_id=20))
    ).cumulative_count == 5
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=11, target_user_id=20))
    ).cumulative_count == 0
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=10, target_user_id=21))
    ).cumulative_count == 0

    # 绕过后台任务启动，只验证数据库恢复和真实发言判断。
    listener = PunishmentListener.__new__(PunishmentListener)
    listener.bot = logic.bot
    listener.active_mutes = {}
    await listener._load_active_mutes_into_cache()
    assert listener.active_mutes == {10: {20: PERMANENT_THREAD_MUTE}}
    service = StructuredSpeechService(logic.bot)
    assert await service.is_user_punished(thread_id=10, user_id=20)


@pytest.mark.asyncio
async def test_kicks_and_off_topic_share_only_counted_records(logic):
    """快速累计、人工处罚交替计数，无限制提交和歪楼滑坡不计数。"""
    await apply(logic)
    kick = await apply(logic, mode=None, voting_allowed=False)
    assert kick.cumulative_count == 2
    third = await apply(logic)
    assert third.cumulative_count == 3
    assert third.reason.endswith("三次处罚")
    assert not third.voting_allowed
    off_topic = await apply(logic, mode="off_topic")
    assert off_topic.cumulative_count == 3
    assert off_topic.mute_end_time == third.mute_end_time
    assert not off_topic.voting_allowed
    noop = await apply(logic, mode=None)
    assert noop.cumulative_count == 3
    async with logic.bot.db_handler.get_session() as session:
        records = (
            await session.exec(select(PunishmentRecord).order_by(PunishmentRecord.id))
        ).all()
        assert [record.counts_toward_cumulative for record in records] == [
            True,
            True,
            True,
            False,
            False,
        ]


@pytest.mark.asyncio
async def test_quick_punishment_preserves_stronger_mute_and_restricted_voting(logic):
    long_mute = datetime.now(timezone.utc) + timedelta(hours=2)
    await apply(logic, mode=None, voting_allowed=False, mute_end_time=long_mute)
    for mode in ("cumulative", "off_topic"):
        result = await apply(logic, mode=mode)
        assert result.mute_end_time == long_mute
        assert not result.voting_allowed
    await apply(logic)
    permanent = await apply(logic)
    assert permanent.mute_end_time == PERMANENT_THREAD_MUTE
    assert (await apply(logic, mode="off_topic")).mute_end_time == PERMANENT_THREAD_MUTE


@pytest.mark.asyncio
async def test_lifting_latest_decrements_once_and_reuses_tier(logic):
    first = await apply(logic)
    await apply(logic)
    third = await apply(logic)
    with pytest.raises(BusinessRuleError, match="后续处罚覆盖"):
        await lift(logic, first)
    assert await lift(logic, third) == 2
    with pytest.raises(BusinessRuleError, match="已经解除"):
        await lift(logic, third)
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=10, target_user_id=20))
    ).cumulative_count == 2
    async with logic.bot.db_handler.get_session() as session:
        record = await session.get(PunishmentRecord, third.punishment_record_id)
        assert record.lifted_at is not None
        assert record.lifted_by_id == 30
        assert record.lift_reason == "解除测试"
        activity = (await session.exec(select(UserActivity))).one()
        assert activity.mute_end_time is None
        assert activity.validation == 1
    assert (await apply(logic)).reason.endswith("三次处罚")


@pytest.mark.asyncio
async def test_lifting_off_topic_does_not_decrement_and_stale_forms_are_rejected(logic):
    first = await apply(logic)
    off_topic = await apply(logic, mode="off_topic")
    with pytest.raises(BusinessRuleError):
        await lift(logic, first)
    assert await lift(logic, off_topic) == 1
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=10, target_user_id=20))
    ).cumulative_count == 1


@pytest.mark.asyncio
async def test_concurrent_instances_serialize_counts_and_cache_events(logic):
    other_logic = PunishmentLogic(logic.bot)
    results = await asyncio.gather(apply(logic), apply(other_logic), apply(logic))
    assert sorted(result.cumulative_count for result in results) == [1, 2, 3]
    updates = logic.bot.dispatch.call_args_list
    assert [call.args[3] for call in updates] == [result.mute_end_time for result in results]
    latest = max(results, key=lambda result: result.punishment_record_id)
    attempts = await asyncio.gather(
        lift(logic, latest), lift(other_logic, latest), return_exceptions=True
    )
    assert sum(isinstance(result, int) for result in attempts) == 1
    assert sum(isinstance(result, BusinessRuleError) for result in attempts) == 1
    assert (
        await logic.get_thread_history(QueryThreadPunishmentQo(thread_id=10, target_user_id=20))
    ).cumulative_count == 2


@pytest.mark.asyncio
async def test_off_topic_race_requires_confirmation_without_writing(logic):
    await apply(logic)
    with pytest.raises(BusinessRuleError, match="重新使用指令"):
        await apply(logic, mode="off_topic", off_topic_confirmed=False)
    async with logic.bot.db_handler.get_session() as session:
        total, _ = await PunishmentRecordRepository(session).get_summary(
            thread_id=10, target_user_id=20
        )
    assert total == 1


@pytest.mark.asyncio
async def test_record_and_activity_roll_back_together_on_failure(logic, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("数据库写入失败")

    monkeypatch.setattr(PunishmentRecordRepository, "create_record", fail)
    with pytest.raises(RuntimeError):
        await apply(logic)
    async with logic.bot.db_handler.get_session() as session:
        assert not (await session.exec(select(UserActivity))).all()
        assert not (await session.exec(select(PunishmentRecord))).all()
    logic.bot.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_expiration_cleanup_cannot_clear_replacement_punishment(logic):
    """缓存旧截止时间过期后，新禁言不应被后台清理覆盖。"""
    await apply(logic)
    async with logic.bot.db_handler.get_session() as session:
        await UserActivityRepository(session).batch_clear_expired_mutes([(20, 10)])
        await session.commit()
    async with logic.bot.db_handler.get_session() as session:
        activity = (await session.exec(select(UserActivity))).one()
        assert activity.mute_end_time > datetime.now(timezone.utc)
        activity.mute_end_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.add(activity)
        await session.commit()
        await UserActivityRepository(session).batch_clear_expired_mutes([(20, 10)])
        await session.commit()
        await session.refresh(activity)
        assert activity.mute_end_time is None


@pytest.mark.asyncio
async def test_history_dto_survives_session_close_and_later_record_changes(logic):
    """历史快照应独立于 ORM 会话，后续数据库更新不改变已取得的快照。"""
    result = await apply(logic)
    history = await logic.get_thread_history(QueryThreadPunishmentQo(10, 20))
    assert isinstance(history.latest, PunishmentRecordDto)
    assert all(isinstance(record, PunishmentRecordDto) for record in history.records)

    async with logic.bot.db_handler.get_session() as session:
        record = await session.get(PunishmentRecord, result.punishment_record_id)
        record.reason = "后续更新"
        session.add(record)
        await session.commit()

    assert history.latest.reason == "请不要歪楼滑坡，一次处罚"
    assert history.records[0].reason == history.latest.reason
    assert history.latest.model_dump()["id"] == result.punishment_record_id


@pytest.mark.asyncio
async def test_history_query_count_does_not_grow_with_record_count(logic):
    """历史查询按批次读取记录，新增历史不会引入逐条查询。"""
    await apply(logic)
    async with logic.bot.db_handler.get_session() as session:
        engine = session.bind.sync_engine
    statements = []

    def record_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        await logic.get_thread_history(QueryThreadPunishmentQo(10, 20))
        initial_count = len(statements)
        for _ in range(5):
            await apply(logic)
        statements.clear()
        history = await logic.get_thread_history(QueryThreadPunishmentQo(10, 20))
        assert len(statements) == initial_count
        assert len(history.records) == 3
        assert history.total == 6
    finally:
        event.remove(engine, "before_cursor_execute", record_query)


@pytest.mark.parametrize(
    "number,expected",
    [(5, "五"), (10, "十"), (11, "十一"), (21, "二十一"), (101, "一百零一"), (110, "一百一十")],
)
def test_reason_uses_actual_chinese_ordinal(number, expected):
    assert chinese_number(number) == expected
