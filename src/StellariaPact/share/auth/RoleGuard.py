import functools
import logging
from typing import Any, Callable, Coroutine, Dict, TypeVar

import discord

from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.StellariaPactBot import StellariaPactBot

# 定义一个类型变量来帮助 mypy 理解被装饰的函数类型
T = TypeVar("T")
logger = logging.getLogger(__name__)


class RoleGuard:
    """
    一个用于创建和检查基于身份组权限的工具类。
    """

    @staticmethod
    def _check_roles(
        member: discord.Member, config_roles: Dict[str, Any], required_role_keys: tuple[str, ...]
    ) -> bool:
        """
        核心的权限检查逻辑。

        Args:
            member: 需要被检查的服务器成员。
            config_roles: 从 bot.config 中获取的身份组配置字典。
            required_role_keys: 一个或多个在 config.json 中定义的身份组键名。

        Returns:
            如果成员拥有至少一个指定的身份组，则返回 True，否则返回 False。
        """
        # 获取用户拥有的所有身份组的 ID
        user_role_ids = {role.id for role in member.roles}

        # 从配置中查找需要的身份组 ID
        required_role_ids = set()
        for key in required_role_keys:
            role_id = config_roles.get(key)
            if not role_id:
                logger.warning(f"权限检查失败：在 config.json 中未找到身份组键 '{key}'")
                continue
            required_role_ids.add(int(role_id))

        # 检查用户身份组和所需身份组是否有交集
        return bool(user_role_ids.intersection(required_role_ids))

    @staticmethod
    def hasRoles(interaction: discord.Interaction, *required_role_keys: str) -> bool:
        """
        检查交互的发起者是否拥有指定的身份组之一。

        Args:
            interaction: 交互的 interaction 对象
            *required_role_keys: 一个或多个在 config.json 中定义的身份组键名。

        Returns:
            如果用户拥有任何一个指定的身份组，则返回 True，否则返回 False。
        """
        # 确保 interaction.user 是 Member 类型，这样才能获取 roles
        if not isinstance(interaction.user, discord.Member):
            return False

        if not hasattr(interaction.client, "config"):
            raise RuntimeError("Bot 不存在 'config' 属性")

        bot: StellariaPactBot = interaction.client
        config_roles = bot.config.get("roles", {})

        return RoleGuard._check_roles(interaction.user, config_roles, required_role_keys)

    @staticmethod
    def requireRoles(*requiredRoleKeys: str) -> Callable[[T], T]:
        """
        一个装饰器，用于检查命令使用者是否拥有指定的身份组之一。
        如果检查失败，它会抛出 MissingRole 异常。

        Args:
            *requiredRoleKeys: 一个或多个在 config.json 中定义的身份组键名。

        Raises:
            MissingRole: 如果用户不拥有任何一个指定的身份组。
        """

        def decorator(
            func: Callable[..., Coroutine[Any, Any, Any]],
        ) -> Callable[..., Coroutine[Any, Any, Any]]:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # 在参数中动态查找 interaction 对象
                # 对于 Cog 中的命令, args 可能是 (self, interaction, ...)
                # 对于普通命令, args 可能是 (interaction, ...)
                interaction: discord.Interaction | None = None
                for arg in args:
                    if isinstance(arg, discord.Interaction):
                        interaction = arg
                        break

                if interaction is None:
                    # 如果在位置参数中没找到，有可能是关键字参数
                    for val in kwargs.values():
                        if isinstance(val, discord.Interaction):
                            interaction = val
                            break

                if interaction is None:
                    logger.error("在权限装饰器中无法找到 'interaction' 对象。")
                    raise RuntimeError("无法在命令上下文中找到 interaction。")

                # 使用新的 hasRoles 方法进行检查
                if not RoleGuard.hasRoles(interaction, *requiredRoleKeys):
                    raise MissingRole()

                # 权限验证通过，执行原始命令
                return await func(*args, **kwargs)

            return wrapper

        return decorator
