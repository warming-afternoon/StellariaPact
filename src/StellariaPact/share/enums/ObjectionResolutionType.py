from enum import IntEnum


class ObjectionResolutionType(IntEnum):
    """异议结束时的处理分类。"""

    NORMAL = 1
    """正常流程。"""

    MALICIOUS = 2
    """恶意违规。"""
