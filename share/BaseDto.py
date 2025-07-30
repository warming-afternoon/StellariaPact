from pydantic import BaseModel

class BaseDto(BaseModel):
    """
    所有 DTO 的基类，统一配置 orm_mode。
    """
    class Config:
        orm_mode = True