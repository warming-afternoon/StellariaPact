"""使用可选的额外 Bot 身份原生转发消息。"""

import asyncio
import math
import os
import time

import aiohttp
import discord

from StellariaPact.share.HttpClient import HttpClient


class MessageForwardError(Exception):
    """仅携带可安全记录的错误信息，不保留 HTTP 响应正文或请求头。"""

    def __init__(self, *, uncertain=False, status=None, code=None):
        self.uncertain = uncertain
        self.status = status
        self.code = code
        super().__init__(
            f"Message forward failed: status={status}, code={code}, uncertain={uncertain}"
        )


class MessageForwardService:
    def __init__(self, token: str = "", proxy: str | None = None):
        self._token = token.strip()
        self._proxy = proxy
        self._lock = asyncio.Lock()
        self._cooldown_until = 0.0

    @classmethod
    def from_env(cls, proxy: str | None = None) -> "MessageForwardService":
        return cls(os.getenv("STELLARIA_FORWARD_BOT_TOKEN", ""), proxy)

    @property
    def uses_extra_token(self) -> bool:
        return bool(self._token)

    @staticmethod
    def _seconds(value) -> float | None:
        try:
            value = float(value)
            return value if math.isfinite(value) and value >= 0 else None
        except (TypeError, ValueError):
            return None

    async def forward(self, source_message: discord.Message, destination) -> int:
        if not self._token:
            return (await source_message.forward(destination)).id
        # 预算从获取锁后开始，避免排队时间侵占 HTTP 请求预算。
        async with self._lock:
            return await self._forward_rest(source_message, destination)

    async def _forward_rest(self, source_message, destination) -> int:
        deadline = time.monotonic() + 30
        reference = {
            "type": 1,
            "channel_id": str(source_message.channel.id),
            "message_id": str(source_message.id),
            "fail_if_not_exists": True,
        }
        if source_message.guild is not None:
            reference["guild_id"] = str(source_message.guild.id)
        payload = {"message_reference": reference, "allowed_mentions": {"parse": []}}
        status = code = None
        for attempt in range(3):
            delay = max(0, self._cooldown_until - time.monotonic())
            if delay >= deadline - time.monotonic():
                raise MessageForwardError(status=status, code=code)
            if delay:
                await asyncio.sleep(delay)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MessageForwardError(status=status, code=code)
            status = code = None
            try:
                response = await HttpClient.post(
                    f"https://discord.com/api/v10/channels/{destination.id}/messages",
                    headers={"Authorization": f"Bot {self._token}"},
                    json=payload,
                    proxy=self._proxy,
                    timeout=aiohttp.ClientTimeout(total=min(10, remaining)),
                    allow_redirects=False,
                )
                async with response:
                    status = response.status
                    reset = self._seconds(response.headers.get("X-RateLimit-Reset-After"))
                    if response.headers.get("X-RateLimit-Remaining") == "0" and reset is not None:
                        self._cooldown_until = max(self._cooldown_until, time.monotonic() + reset)
                    try:
                        data = await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    code = data.get("code") if type(data.get("code")) is int else None
                    if 200 <= status < 300:
                        message_id = data.get("id")
                        if isinstance(message_id, (int, str)) and not isinstance(message_id, bool):
                            try:
                                if int(message_id) > 0:
                                    return int(message_id)
                            except ValueError:
                                pass
                        raise MessageForwardError(uncertain=True, status=status, code=code)
                    if status == 429:
                        retry_after = self._seconds(data.get("retry_after"))
                        if retry_after is None:
                            retry_after = self._seconds(response.headers.get("Retry-After"))
                        if retry_after is not None:
                            self._cooldown_until = max(
                                self._cooldown_until, time.monotonic() + retry_after
                            )
                            if attempt < 2:
                                continue
                    raise MessageForwardError(uncertain=status >= 500, status=status, code=code)
            except (aiohttp.ClientError, TimeoutError):
                # 不传播底层异常，避免调度器的异常日志泄露请求凭据。
                raise MessageForwardError(uncertain=True, status=status, code=code) from None
        raise MessageForwardError(status=status, code=code)
