from typing import Optional
from sqlmodel import Field, SQLModel
from humps import camelize, decamelize

def to_snake_case(s: str) -> str:
    """将驼峰命名转换为蛇形命名"""
    return decamelize(s)

class BaseModel(SQLModel):
    """
    所有数据模型的基类
    提供了共享的配置和通用字段，并自动处理命名转换
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        """
        Pydantic 的共享配置
        - orm_mode: 允许从 ORM 对象创建 Pydantic 模型
        - allow_population_by_field_name: 允许使用字段名填充
        - alias_generator: 自动将驼峰字段名转换为蛇形数据库列名
        """
        orm_mode = True
        allow_population_by_field_name = True
        alias_generator = to_snake_case