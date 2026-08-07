"""接收 Odysseia-protect 转发的消息资格事件。"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os

import discord
from aiohttp import web
from discord.ext import commands

from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.listeners.MessageEvent import MessageEvent
from StellariaPact.cogs.Voting.views import VoteEmbedBuilder
from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.qo.user_activity import UpdateUserActivityQo
from StellariaPact.share import DiscordUtils, StellariaPactBot

logger = logging.getLogger(__name__)

MESSAGE_EVENT_PATH = "/api/v1/message-events"
HEALTH_PATH = "/healthz"
MAX_REQUEST_SIZE = 16 * 1024


class MessageEventApiCog(commands.Cog):
    """接收并处理下载 Bot 转发的消息资格事件。"""

    def __init__(self, bot: StellariaPactBot, voting_cog: Voting):
        """初始化消息事件 API Cog。"""
        # 保存业务依赖并读取 HTTP 监听配置。
        self.bot = bot
        self.voting_cog = voting_cog
        self.bind_host = os.getenv("STELLARIA_EVENT_API_BIND_HOST", "0.0.0.0").strip()
        self.bind_port = self._parse_port(os.getenv("STELLARIA_EVENT_API_PORT", "8765"))
        self.token = os.getenv("STELLARIA_EVENT_API_TOKEN", "").strip()

        # 初始化 aiohttp 服务生命周期对象。
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.application = self._build_application()

    @staticmethod
    def _parse_port(value: str) -> int | None:
        """解析并校验 HTTP 监听端口。"""
        # 非整数端口视为无效配置。
        try:
            port = int(value)
        except ValueError:
            return None

        # TCP 端口必须处于合法范围。
        return port if 1 <= port <= 65535 else None

    def _build_application(self) -> web.Application:
        """创建带请求体限制和固定路由的 aiohttp 应用。"""
        # 限制请求体大小，避免无关大请求占用内存。
        application = web.Application(client_max_size=MAX_REQUEST_SIZE)

        # 注册健康检查和消息事件入口。
        application.router.add_get(HEALTH_PATH, self._health)
        application.router.add_post(MESSAGE_EVENT_PATH, self._handle_message_event)
        return application

    async def cog_load(self) -> None:
        """加载 Cog 时启动内部 HTTP 服务。"""
        # 缺少共享令牌时拒绝暴露未鉴权接口。
        if not self.token:
            logger.critical(
                "STELLARIA_EVENT_API_TOKEN is missing; the message event API was not started."
            )
            return

        # 主机或端口无效时保留 Bot 其他功能并跳过 API 启动。
        if not self.bind_host or self.bind_port is None:
            logger.critical(
                "Invalid Stellaria message event API bind configuration: host=%r port=%r",
                self.bind_host,
                self.bind_port,
            )
            return

        # 创建并绑定 aiohttp 服务，失败时完整清理已分配资源。
        runner = web.AppRunner(self.application)
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.bind_host, self.bind_port)
            await site.start()
        except Exception:
            await runner.cleanup()
            logger.exception("Failed to start the Stellaria message event API.")
            return

        # 记录已启动的服务对象供卸载流程清理。
        self._runner = runner
        self._site = site
        logger.info(
            "Stellaria message event API listening on %s:%s",
            self.bind_host,
            self.bind_port,
        )

    async def cog_unload(self) -> None:
        """卸载 Cog 时关闭内部 HTTP 服务。"""
        # AppRunner 会统一关闭站点和活动连接。
        if self._runner is not None:
            await self._runner.cleanup()
        self._site = None
        self._runner = None

    async def _health(self, request: web.Request) -> web.Response:
        """返回不包含敏感配置的健康状态。"""
        # 保留请求参数以符合 aiohttp 处理器签名。
        del request
        return web.json_response({"status": "ok"})

    def _is_authorized(self, request: web.Request) -> bool:
        """使用常量时间比较验证 Bearer Token。"""
        # 从请求头提取完整 Bearer 凭据。
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"

        # 空令牌永远不能通过验证。
        return bool(self.token) and hmac.compare_digest(supplied, expected)

    def _matches_config(self, event: MessageEvent) -> bool:
        """校验事件服务器和论坛是否匹配 Bot 配置。"""
        # 接收端使用自身配置进行二次来源校验。
        configured_guild = self.bot.config.get("guild_id")
        configured_forum = self.bot.config.get("channels", {}).get("discussion")
        try:
            return event.guild_id == int(configured_guild) and event.forum_id == int(
                configured_forum
            )
        except (TypeError, ValueError):
            # 本地配置无效时拒绝所有外部事件。
            return False

    async def _handle_message_event(self, request: web.Request) -> web.Response:
        """验证并处理单个跨 Bot 消息事件。"""
        # 在解析请求体前完成身份验证。
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        if request.content_type != "application/json":
            return web.json_response({"error": "content type must be JSON"}, status=400)

        # 使用独立事件类型严格校验 HTTP 数据契约。
        try:
            payload = await request.json()
            event = MessageEvent.from_payload(payload)
        except (ValueError, TypeError, web.HTTPException) as exc:
            return web.json_response({"error": str(exc)}, status=400)

        # 拒绝其他服务器或论坛伪造的资格事件。
        if not self._matches_config(event):
            return web.json_response(
                {"error": "guild_id or forum_id does not match configuration"},
                status=422,
            )

        # Cog 只组装单次业务请求，不直接访问数据库或 Repository。
        qo = UpdateUserActivityQo(
            user_id=event.user_id,
            thread_id=event.thread_id,
            change=1 if event.event_type == "message_created" else -1,
        )
        try:
            if event.event_type == "message_created":
                # 创建事件交由服务层增加用户活动计数。
                await self.voting_cog.logic.handle_message_creation(qo)
            else:
                # 删除事件由服务层统一处理计数、资格和跨表撤票。
                details_to_update = await self.voting_cog.logic.handle_message_deletion(qo)
                try:
                    await self._refresh_vote_panels(event.thread_id, details_to_update)
                except Exception:
                    # 数据事务已经成功时，面板刷新失败不改变接口结果。
                    logger.exception(
                        "Message %s was processed, but vote panel refresh failed.",
                        event.message_id,
                    )
        except Exception:
            # 业务处理失败时返回明确错误，但不在接收端自动重试。
            logger.exception(
                "Failed to process %s for message %s in thread %s.",
                event.event_type,
                event.message_id,
                event.thread_id,
            )
            return web.json_response({"error": "event processing failed"}, status=500)

        # 所有数据库逻辑完成后确认事件已处理。
        return web.json_response({"status": "processed"})

    async def _refresh_vote_panel(
        self,
        thread: discord.Thread,
        details: VoteDetailDto,
    ) -> None:
        """刷新单个受资格变化影响的投票面板。"""
        # 没有上下文消息 ID 的投票无需刷新 Discord 消息。
        if not details.context_message_id:
            return

        try:
            # 每个面板只获取一次对应 Discord 消息。
            message = await thread.fetch_message(details.context_message_id)
            embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=thread.name,
                vote_details=details,
            )

            # 统一通过 API 调度器提交编辑请求以遵守限流策略。
            await self.bot.api_scheduler.submit(message.edit(embeds=embeds), priority=2)
        except (discord.NotFound, discord.Forbidden):
            logger.warning(
                "Vote panel message %s could not be fetched in thread %s.",
                details.context_message_id,
                thread.id,
            )
        except IndexError:
            logger.warning(
                "Vote panel message %s has no usable embed.",
                details.context_message_id,
            )

    async def _refresh_vote_panels(
        self,
        thread_id: int,
        details_to_update: list[VoteDetailDto] | None,
    ) -> None:
        """并发刷新资格变化影响的全部投票面板。"""
        # 服务层一次性返回全部面板数据，避免循环内重复查询数据库。
        if not details_to_update:
            return

        # 帖子对象只解析一次并复用于所有面板刷新。
        thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
        if thread is None:
            logger.warning("Cannot refresh vote panels: thread %s was not found.", thread_id)
            return

        # 并发处理独立 Discord 消息，避免串行外部请求形成 N+1 延迟。
        results = await asyncio.gather(
            *(self._refresh_vote_panel(thread, details) for details in details_to_update),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                # 单个面板失败不会阻塞其他面板完成刷新。
                logger.error(
                    "Failed to update a vote panel after message deletion.",
                    exc_info=(type(result), result, result.__traceback__),
                )
