from typing import Any, Dict

from discord.ext import commands

from StellariaPact.share.ApiScheduler import APIScheduler
from StellariaPact.share.DatabaseHandler import DatabaseHandler
from StellariaPact.share.TimeUtils import TimeUtils


class StellariaPactBot(commands.Bot):
    """
    自定义 Bot 基类。
    它继承自 commands.Bot，并为项目中的自定义属性（如 api_scheduler）
    提供一个集中的定义，以便在整个项目中获得准确的类型提示。
    """

    api_scheduler: APIScheduler
    db_handler: DatabaseHandler
    config: Dict[str, Any]
    time_utils: TimeUtils
