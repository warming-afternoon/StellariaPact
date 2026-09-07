from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from StellariaPact.share.HttpClient import HttpClient
from StellariaPact.share.MessageForwardService import MessageForwardError, MessageForwardService


def response(status=200, data=None, headers=None):
    result = MagicMock(status=status, headers=headers or {})
    result.json = AsyncMock(return_value=data if data is not None else {"id": "123"})
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


@pytest.fixture
def messages():
    source = SimpleNamespace(
        id=100,
        channel=SimpleNamespace(id=30),
        guild=SimpleNamespace(id=10),
        forward=AsyncMock(return_value=SimpleNamespace(id=123)),
    )
    return source, SimpleNamespace(id=99)


@pytest.mark.parametrize("token", [None, "", "  ", " privileged "])
@pytest.mark.parametrize("remote", ["true", "false"])
def test_env(monkeypatch, token, remote):
    monkeypatch.setenv("STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED", remote)
    monkeypatch.delenv("STELLARIA_FORWARD_BOT_TOKEN", raising=False)
    if token is not None:
        monkeypatch.setenv("STELLARIA_FORWARD_BOT_TOKEN", token)
    assert MessageForwardService.from_env().uses_extra_token == bool(token and token.strip())


@pytest.mark.asyncio
async def test_original_identity(monkeypatch, messages):
    post = AsyncMock()
    monkeypatch.setattr(HttpClient, "post", post)
    assert await MessageForwardService().forward(*messages) == 123
    messages[0].forward.assert_awaited_once_with(messages[1])
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_payload_and_session_isolation(monkeypatch, messages):
    session = SimpleNamespace(closed=False, post=AsyncMock(return_value=response()), headers={})
    monkeypatch.setattr(HttpClient, "_session", session)
    service = MessageForwardService(" privileged ", "http://proxy")
    assert await service.forward(*messages) == 123
    args, kwargs = session.post.call_args
    assert args == ("https://discord.com/api/v10/channels/99/messages",)
    assert kwargs["headers"] == {"Authorization": "Bot privileged"}
    assert kwargs["proxy"] == "http://proxy"
    assert kwargs["timeout"].total == 10
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"] == {
        "message_reference": {
            "type": 1,
            "guild_id": "10",
            "channel_id": "30",
            "message_id": "100",
            "fail_if_not_exists": True,
        },
        "allowed_mentions": {"parse": []},
    }
    assert session.headers == {}
    messages[0].forward.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,uncertain",
    [
        (401, 0, False),
        (403, 50013, False),
        (404, 10008, False),
        (400, 160014, False),
        (400, 50035, False),
        (500, 0, True),
        (200, 0, True),
    ],
)
async def test_failure_no_retry(monkeypatch, messages, status, code, uncertain):
    post = AsyncMock(return_value=response(status, {"code": code, "message": "secret"}))
    monkeypatch.setattr(HttpClient, "post", post)
    with pytest.raises(MessageForwardError) as caught:
        await MessageForwardService("secret").forward(*messages)
    assert caught.value.uncertain is uncertain
    assert caught.value.status == status
    assert "secret" not in str(caught.value)
    assert post.await_count == 1
    messages[0].forward.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("secret"), aiohttp.ClientError("secret")])
async def test_transport_uncertain(monkeypatch, messages, error):
    post = AsyncMock(side_effect=error)
    monkeypatch.setattr(HttpClient, "post", post)
    with pytest.raises(MessageForwardError) as caught:
        await MessageForwardService("secret").forward(*messages)
    assert caught.value.uncertain
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_after,success,count", [(0, True, 2), (0, False, 3), (31, False, 1)]
)
async def test_rate_limit_budget(monkeypatch, messages, retry_after, success, count):
    limited = response(429, {"retry_after": retry_after})
    post = AsyncMock(side_effect=[limited, response()] if success else [limited] * 3)
    monkeypatch.setattr(HttpClient, "post", post)
    service = MessageForwardService("secret")
    if success:
        assert await service.forward(*messages) == 123
    else:
        with pytest.raises(MessageForwardError) as caught:
            await service.forward(*messages)
        assert not caught.value.uncertain
    assert post.await_count == count


@pytest.mark.asyncio
async def test_cooldown_between_calls(monkeypatch, messages):
    clock = [100.0]
    monkeypatch.setattr(
        "StellariaPact.share.MessageForwardService.time.monotonic", lambda: clock[0]
    )

    async def sleep(delay):
        clock[0] += delay

    wait = AsyncMock(side_effect=sleep)
    monkeypatch.setattr("StellariaPact.share.MessageForwardService.asyncio.sleep", wait)
    post = AsyncMock(
        side_effect=[
            response(headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "2"}),
            response(),
        ]
    )
    monkeypatch.setattr(HttpClient, "post", post)
    service = MessageForwardService("secret")
    await service.forward(*messages)
    await service.forward(*messages)
    wait.assert_awaited_once_with(2)
