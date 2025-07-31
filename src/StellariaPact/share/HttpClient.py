from typing import Any, Optional

import aiohttp


class HttpClient:
    _session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def _get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
        return cls._session

    @classmethod
    async def get(cls, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        session = cls._get_session()
        return await session.get(url, **kwargs)

    @classmethod
    async def post(cls, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        session = cls._get_session()
        return await session.post(url, **kwargs)

    @classmethod
    async def close(cls) -> None:
        if cls._session and not cls._session.closed:
            await cls._session.close()
