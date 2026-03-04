import logging
import math
from functools import partial

import discord

from StellariaPact.cogs.Voting.dto import OptionResult
from StellariaPact.cogs.Voting.views import DeleteOptionModal
from StellariaPact.share import StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class PaginatedManageView(discord.ui.View):
    """
    支持翻页的投票管理视图
    最多显示4个选项，每个选项有赞成、反对、弃票三个按钮
    底部有分页导航按钮
    """

    message: discord.Message | discord.WebhookMessage | None = None

    def __init__(
        self,
        bot: StellariaPactBot,
        interaction: discord.Interaction,
        thread_id: int,
        msg_id: int,
        options: list[OptionResult],
        option_type: int,
        page: int = 0,
    ):
        super().__init__(timeout=900)  # 15分钟超时
        self.bot = bot
        self.interaction = interaction
        self.thread_id = thread_id
        self.msg_id = msg_id
        self.options = options
        self.option_type = option_type  # 0-普通, 1-异议
        self.page = page

        self.items_per_page = 4
        self.total_pages = max(1, math.ceil(len(options) / self.items_per_page))

        self._build_ui()

    def _build_ui(self):
        """动态构建UI按钮"""
        self.clear_items()

        # 切片获取当前页的选项 (最多4个)
        start_idx = self.page * self.items_per_page
        current_options = self.options[start_idx : start_idx + self.items_per_page]

        prefix = "选项" if self.option_type == 0 else "异议"

        # 生成操作按钮 (行 0 到 3)
        for i, opt in enumerate(current_options):
            # 赞成按钮
            btn_app = discord.ui.Button(
                label=f"赞成{prefix} {opt.choice_index}",
                style=discord.ButtonStyle.success,
                row=i
            )
            btn_app.callback = partial(self._cast_vote, choice=1, choice_index=opt.choice_index)

            # 反对按钮
            btn_rej = discord.ui.Button(
                label=f"反对{prefix} {opt.choice_index}",
                style=discord.ButtonStyle.danger,
                row=i
            )
            btn_rej.callback = partial(self._cast_vote, choice=0, choice_index=opt.choice_index)

            # 弃票按钮 (删除投票记录)
            btn_abs = discord.ui.Button(
                label=f"{prefix} {opt.choice_index} 弃票",
                style=discord.ButtonStyle.secondary,
                row=i
            )
            btn_abs.callback = partial(self._cast_vote, choice=None, choice_index=opt.choice_index)

            self.add_item(btn_app)
            self.add_item(btn_rej)
            self.add_item(btn_abs)

            # 如果是该选项的创建人，则增加删除按钮
            if opt.creator_id == self.interaction.user.id and opt.option_id is not None:
                btn_del = discord.ui.Button(
                    label=f"删除{prefix}",
                    style=discord.ButtonStyle.danger,
                    row=i
                )
                btn_del.callback = partial(self._delete_option, opt=opt)
                self.add_item(btn_del)

        # 在选项数 > 4 时生成底部分页按钮 (行 4)
        if len(self.options) > self.items_per_page:
            btn_first = discord.ui.Button(
                emoji="⏪",
                style=discord.ButtonStyle.primary,
                row=4,
                disabled=(self.page == 0)
            )
            btn_first.callback = partial(self._change_page, new_page=0)

            btn_prev = discord.ui.Button(
                emoji="◀",
                style=discord.ButtonStyle.primary,
                row=4,
                disabled=(self.page == 0)
            )
            btn_prev.callback = partial(self._change_page, new_page=self.page - 1)

            btn_indicator = discord.ui.Button(
                label=f"{self.page + 1} / {self.total_pages}",
                style=discord.ButtonStyle.blurple,
                row=4,
                disabled=True
            )

            btn_next = discord.ui.Button(
                emoji="▶",
                style=discord.ButtonStyle.primary,
                row=4,
                disabled=(self.page >= self.total_pages - 1)
            )
            btn_next.callback = partial(self._change_page, new_page=self.page + 1)

            btn_last = discord.ui.Button(
                emoji="⏩",
                style=discord.ButtonStyle.primary,
                row=4,
                disabled=(self.page >= self.total_pages - 1)
            )
            btn_last.callback = partial(self._change_page, new_page=self.total_pages - 1)

            self.add_item(btn_first)
            self.add_item(btn_prev)
            self.add_item(btn_indicator)
            self.add_item(btn_next)
            self.add_item(btn_last)

    async def on_timeout(self) -> None:
        """
        当视图超时后自动调用此方法。
        """
        if self.message:
            try:
                await self.bot.api_scheduler.submit(
                    self.message.delete(),
                    priority=5,
                )
            except discord.NotFound:
                # 如果消息已被用户删除，则忽略
                pass
            except Exception as e:
                logger.error(f"删除超时的分页管理面板时出错: {e}")

    async def _change_page(self, interaction: discord.Interaction, new_page: int):
        """切换页面"""
        self.page = new_page
        self._build_ui()
        await interaction.response.edit_message(view=self)

    async def _cast_vote(
        self,
        interaction: discord.Interaction,
        choice: int | None,
        choice_index: int,
    ):
        """处理投票操作"""
        await safeDefer(interaction)
        # 派发统一下层逻辑，附带 option_type
        self.bot.dispatch(
            "user_vote_submitted",
            interaction,
            self.msg_id,
            self.thread_id,
            self.option_type,
            choice_index,
            choice,
            self,
        )

    async def _delete_option(self, interaction: discord.Interaction, opt: OptionResult):
        """弹出删除确认理由模态框"""

        if opt.option_id is None:
            await interaction.response.send_message("发生错误：无法获取选项 ID。", ephemeral=True)
            return

        modal = DeleteOptionModal(
            bot=self.bot,
            message_id=self.msg_id,
            thread_id=self.thread_id,
            option_id=opt.option_id,
            option_type=self.option_type,
            choice_index=opt.choice_index,
            option_text=opt.choice_text,
            manage_view=self
        )
        await interaction.response.send_modal(modal)
