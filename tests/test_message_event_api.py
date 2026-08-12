from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from StellariaPact.cogs.Voting.listeners.MessageEventApiCog import MessageEventApiCog
from StellariaPact.share.RemoteMessageEventsConfig import (
    RemoteMessageEventsConfig,
)

REMOTE_CONFIG = RemoteMessageEventsConfig(
    enabled=True,
    bind_host="127.0.0.1",
    bind_port=8765,
    token="shared-secret",
)


def make_cog() -> tuple[MessageEventApiCog, MagicMock]:
    bot = MagicMock()
    bot.config = {"guild_id": 100, "channels": {"discussion": 200}}
    voting_cog = MagicMock()
    voting_cog.logic.handle_message_creation = AsyncMock()
    voting_cog.logic.handle_message_deletion = AsyncMock(return_value=None)
    cog = MessageEventApiCog(bot, voting_cog, REMOTE_CONFIG)
    return cog, voting_cog


def event_payload(event_type: str = "message_created") -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "message_id": "300",
        "guild_id": "100",
        "forum_id": "200",
        "thread_id": "400",
        "user_id": "500",
    }


@pytest.mark.asyncio
async def test_health_and_authentication():
    cog, voting_cog = make_cog()
    async with TestClient(TestServer(cog.application)) as client:
        health = await client.get("/healthz")
        health_payload = await health.json()
        unauthorized = await client.post("/api/v1/message-events", json=event_payload())

    assert health.status == 200
    assert health_payload == {"status": "ok"}
    assert unauthorized.status == 401
    voting_cog.logic.handle_message_creation.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_event_routes_to_existing_voting_logic():
    cog, voting_cog = make_cog()
    headers = {"Authorization": "Bearer shared-secret"}
    async with TestClient(TestServer(cog.application)) as client:
        response = await client.post(
            "/api/v1/message-events",
            json=event_payload(),
            headers=headers,
        )

    assert response.status == 200
    qo = voting_cog.logic.handle_message_creation.await_args.args[0]
    assert (qo.user_id, qo.thread_id, qo.change) == (500, 400, 1)


@pytest.mark.asyncio
async def test_deletion_refresh_failure_does_not_fail_processed_event():
    cog, voting_cog = make_cog()
    cog._refresh_vote_panels = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
    headers = {"Authorization": "Bearer shared-secret"}
    async with TestClient(TestServer(cog.application)) as client:
        response = await client.post(
            "/api/v1/message-events",
            json=event_payload("message_deleted"),
            headers=headers,
        )

    assert response.status == 200
    qo = voting_cog.logic.handle_message_deletion.await_args.args[0]
    assert (qo.user_id, qo.thread_id, qo.change) == (500, 400, -1)


@pytest.mark.asyncio
async def test_rejects_unknown_fields_and_wrong_origin():
    cog, voting_cog = make_cog()
    headers = {"Authorization": "Bearer shared-secret"}
    unknown_field_payload = event_payload()
    unknown_field_payload["content"] = "must not be forwarded"
    wrong_origin_payload = event_payload()
    wrong_origin_payload["forum_id"] = "999"
    wrong_version_payload = event_payload()
    wrong_version_payload["schema_version"] = 1.0

    async with TestClient(TestServer(cog.application)) as client:
        invalid = await client.post(
            "/api/v1/message-events",
            json=unknown_field_payload,
            headers=headers,
        )
        wrong_origin = await client.post(
            "/api/v1/message-events",
            json=wrong_origin_payload,
            headers=headers,
        )
        wrong_version = await client.post(
            "/api/v1/message-events",
            json=wrong_version_payload,
            headers=headers,
        )

    assert invalid.status == 400
    assert wrong_origin.status == 422
    assert wrong_version.status == 400
    voting_cog.logic.handle_message_creation.assert_not_awaited()
