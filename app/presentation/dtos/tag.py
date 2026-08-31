from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class TagLeafOutput(BaseModel):
    id: UUID
    name: str
    type: Literal["MICRO"]


class TagNodeOutput(BaseModel):
    id: UUID
    name: str
    type: Literal["MACRO"]
    children: list[TagLeafOutput]
