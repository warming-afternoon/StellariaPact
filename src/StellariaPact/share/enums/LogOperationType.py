from enum import IntEnum


class LogOperationType(IntEnum):
    """操作类型枚举"""

    PROPOSAL = 1
    """提案操作"""

    INTAKE = 2
    """草案操作"""

    PUNISHMENT = 3
    """全局提案处罚操作"""
