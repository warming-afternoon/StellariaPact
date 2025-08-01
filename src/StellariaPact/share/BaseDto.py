from pydantic import BaseModel, ConfigDict


class BaseDto(BaseModel):
    """
    所有 DTO 的基类，统一配置。
    """

    model_config = ConfigDict(from_attributes=True)
