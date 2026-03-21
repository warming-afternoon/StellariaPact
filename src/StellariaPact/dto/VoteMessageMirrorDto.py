from datetime import datetime

from sqlmodel import Field

from StellariaPact.share import BaseDto


class VoteMessageMirrorDto(BaseDto):
    """
    投票消息镜像的数据传输对象
    """

    id: int = Field(..., description="镜像记录的唯一标识符")
    """主键ID"""

    session_id: int = Field(..., description="关联的投票会话ID")
    """关联的投票会话ID"""

    guild_id: int = Field(..., description="服务器ID")
    """服务器ID"""

    channel_id: int = Field(..., description="镜像所在的频道或帖子ID")
    """镜像所在的频道或帖子ID"""

    message_id: int = Field(..., description="镜像消息的ID")
    """镜像消息的ID"""

    created_at: datetime = Field(..., description="创建时间")
    """创建时间"""
