from typing import Any, Dict, Optional

from humps import decamelize
from sqlmodel import Field, SQLModel
from sqlmodel.main import SQLModelMetaclass


def to_snake_case(s: str) -> str:
    """将驼峰命名转换为蛇形命名"""
    return decamelize(s)


class CustomSQLModelMetaclass(SQLModelMetaclass):
    """
    自定义元类，在模型类创建后，自动将驼峰字段名映射到蛇形数据库列名。
    """

    def __new__(cls, name: str, bases: tuple, dct: Dict[str, Any], **kwargs: Any):
        # 首先，让父元类完成所有的标准初始化工作
        new_cls = super().__new__(cls, name, bases, dct, **kwargs)

        # 如果类没有 __sqlmodel_fields__ 属性，说明它不是一个有效的SQLModel模型，直接返回
        if not hasattr(new_cls, "__sqlmodel_fields__"):
            return new_cls

        # 遍历最终生成的所有模型字段
        for field_name, model_field in new_cls.__sqlmodel_fields__.items():
            # 检查字段对应的 SQLAlchemy 列是否存在且列名与字段名相同
            # （这表明它是由SQLModel自动生成的，而不是用户自定义的）
            if model_field.sa_column is not None and model_field.sa_column.name == field_name:
                snake_case_name = to_snake_case(field_name)
                # 如果蛇形名称与驼峰名称不同，则更新列名
                if field_name != snake_case_name:
                    model_field.sa_column.name = snake_case_name

        return new_cls


class BaseModel(SQLModel, metaclass=CustomSQLModelMetaclass):
    """
    所有数据模型的基类。
    - 使用自定义元类自动处理列名转换。
    - 提供共享的配置和通用字段。
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        """
        Pydantic 的共享配置
        """

        from_attributes = True
        validate_by_name = True
        alias_generator = to_snake_case
