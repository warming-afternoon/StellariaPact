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
    默认样式：每行1个选项（赞成/反对/弃票），最多4行
    简洁样式：每行2个选项（仅支持/撤回），最多4行（共8个选项）
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
        ui_style: int = 1,
        user_votes: dict | None = None
    ):
        super().__init__(timeout=900)  # 15分钟超时
        self.bot = bot
        self.interaction = interaction
        self.thread_id = thread_id
        self.msg_id = msg_id
        self.options = options
        self.option_type = option_type  # 0-普通, 1-异议
        self.page = page
        self.ui_style = ui_style
        self.user_votes = user_votes or {}

        # 简洁样式(仅普通投票)使用每页8项（每行2个，共4行）
        # 默认样式使用每页4项（每行1个，共4行）
        if self.ui_style == 2 and self.option_type == 0:
            self.items_per_page = 8
        else:
            self.items_per_page = 4

        self.total_pages = max(1, math.ceil(len(options) / self.items_per_page))
        self._build_ui()

    def _build_ui(self):
        """动态构建UI按钮"""
        self.clear_items()

        start_idx = self.page * self.items_per_page
        current_options = self.options[start_idx : start_idx + self.items_per_page]
        prefix = "选项" if self.option_type == 0 else "异议"

        if self.ui_style == 2 and self.option_type == 0:
            # 简洁样式 (一行两个选项，最多4行)
            for idx, opt in enumerate(current_options):
                row = idx // 2  # 0,1,2,3 对应四行
                is_supported = self.user_votes.get((self.option_type, opt.choice_index)) == 1

                if is_supported:
                    btn = discord.ui.Button(
                        label=f"撤回支持选项 {opt.choice_index}",
                        style=discord.ButtonStyle.secondary,
                        row=row
                    )
                    btn.callback = partial(self._cast_vote, choice=None, choice_index=opt.choice_index)
                else:
                    btn = discord.ui.Button(
                        label=f"支持选项 {opt.choice_index}",
                        style=discord.ButtonStyle.success,
                        row=row
                    )
                    btn.callback = partial(self._cast_vote, choice=1, choice_index=opt.choice_index)
                self.add_item(btn)

                # 如果是创建人，添加删除按钮
                if opt.creator_id == self.interaction.user.id and opt.option_id is not None:
                    del_btn = discord.ui.Button(
                        label=f"删除选项 {opt.choice_index}",
                        style=discord.ButtonStyle.danger,
                        row=row
                    )
                    del_btn.callback = partial(self._delete_option, opt=opt)
                    self.add_item(del_btn)
        else:
            # 默认样式 (每行一个选项的赞成/反对/弃票)
            for i, opt in enumerate(current_options):
                btn_app = discord.ui.Button(
                    label=f"赞成{prefix} {opt.choice_index}",
                    style=discord.ButtonStyle.success,
                    row=i
                )
                btn_app.callback = partial(self._cast_vote, choice=1, choice_index=opt.choice_index)

                btn_rej = discord.ui.Button(
                    label=f"反对{prefix} {opt.choice_index}",
                    style=discord.ButtonStyle.danger,
                    row=i
                )
                btn_rej.callback = partial(self._cast_vote, choice=0, choice_index=opt.choice_index)

                btn_abs = discord.ui.Button(
                    label=f"{prefix} {opt.choice_index} 弃票",
                    style=discord.ButtonStyle.secondary,
                    row=i
                )
                btn_abs.callback = partial(self._cast_vote, choice=None, choice_index=opt.choice_index)

                self.add_item(btn_app)
                self.add_item(btn_rej)
                self.add_item(btn_abs)

                # 如果是创建人，添加删除按钮
                if opt.creator_id == self.interaction.user.id and opt.option_id is not None:
                    btn_del = discord.ui.Button(
                        label=f"删除{prefix}",
                        style=discord.ButtonStyle.danger,
                        row=i
                    )
                    btn_del.callback = partial(self._delete_option, opt=opt)
                    self.add_item(btn_del)

        # 翻页按钮（固定在行4）
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
        """当视图超时后自动调用此方法"""
        if self.message:
            try:
                await self.bot.api_scheduler.submit(
                    self.message.delete(),
                    priority=5,
                )
            except discord.NotFound:
                pass  # 消息已被用户删除
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
