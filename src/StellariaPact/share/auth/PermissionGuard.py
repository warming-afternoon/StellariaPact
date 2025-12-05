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
        1. 用户是管理员。
        2. 用户是当前帖子关联提案的发起人。
        """
        # 1. 检查是否为管理员 (静态角色权限)
        if RoleGuard.hasRoles(interaction, "councilModerator", "executionAuditor"):
            return True

        # 2. 检查是否为提案人 (动态所有权权限)
        if not isinstance(interaction.channel, discord.Thread):
            return False

        bot: StellariaPactBot = interaction.client  # type: ignore
        async with UnitOfWork(bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(interaction.channel.id)
            if proposal and proposal.proposer_id == interaction.user.id:
                return True

        return False
