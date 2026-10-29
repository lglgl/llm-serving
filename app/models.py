from typing import Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False


class ModelInfo(BaseModel):
    id: str
    object: str = "model"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]
