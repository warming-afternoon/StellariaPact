import discord

from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork


class PermissionGuard:
    @staticmethod
    async def can_manage_vote(interaction: discord.Interaction) -> bool:
        """
        检查用户是否可以管理当前上下文中的投票。
        满足以下任一条件即可：
        1. 用户是管理员 (councilModerator, executionAuditor, stewards)。
        2. 用户是当前帖子关联提案的发起人。
        """
        # 检查是否为管理员 (静态角色权限)
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor", "stewards"):
            return True

        # 检查是否为提案人 (动态所有权权限)
        if not isinstance(interaction.channel, discord.Thread):
            return False

        bot: StellariaPactBot = interaction.client  # type: ignore
        async with UnitOfWork(bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(interaction.channel.id)
            if proposal and proposal.proposer_id == interaction.user.id:
                return True

        return False

    @staticmethod
    async def can_manage_rules_or_options(
        interaction: discord.Interaction, thread_id: int | None = None
    ) -> bool:
        """
        检查用户是否可以管理投票规则或创建投票选项。
        满足以下任一条件即可：
        1. 用户有 councilModerator、executionAuditor 或 stewards 身份。
        2. 用户是当前帖子关联提案的发起人。
        """
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor", "stewards"):
            return True

        # 如果未传入 thread_id，则尝试从交互频道获取（兼容讨论帖内操作）
        target_thread_id = thread_id
        if target_thread_id is None and isinstance(interaction.channel, discord.Thread):
            target_thread_id = interaction.channel.id

        if target_thread_id is None:
            return False

        bot: StellariaPactBot = interaction.client # type: ignore
        async with UnitOfWork(bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(target_thread_id)
            if proposal and proposal.proposer_id == interaction.user.id:
                return True
        return False

    @staticmethod
    async def can_create_options(
        interaction: discord.Interaction, thread_id: int | None = None, option_type: int = 0
    ) -> bool:
        """
        检查用户是否可以创建投票选项/异议。
        满足以下任一条件即可：
        1. 用户有 councilModerator、executionAuditor 或 stewards 身份。
        2. 用户是当前帖子关联提案的发起人。
        3. 如果是异议 (option_type == 1)：用户在当前帖子中的有效发言数 > 10，并且拥有 社区建设者 身份。
        """
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor", "stewards"):
            return True

        target_thread_id = thread_id
        if target_thread_id is None and isinstance(interaction.channel, discord.Thread):
            target_thread_id = interaction.channel.id

        if target_thread_id is None:
            return False

        bot: StellariaPactBot = interaction.client # type: ignore
        async with UnitOfWork(bot.db_handler) as uow:
            # 检查是否为提案人
            proposal = await uow.proposal.get_proposal_by_thread_id(target_thread_id)
            if proposal and proposal.proposer_id == interaction.user.id:
                return True

            # 检查有效发言数是否大于 10 并且具有 社区建设者 身份组 (仅允许创建异议)
            if option_type == 1:
                activity = await uow.user_activity.get_user_activity(
                    interaction.user.id, target_thread_id
                )
                if activity and activity.message_count > 10:
                    if RoleGuard.hasRoles(interaction, "communityBuilder"):
                        return True

        return False
