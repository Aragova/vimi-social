from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class PublicationCreateRequest(BaseModel):
    operation_key: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    metric: str = Field(default="publication", min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1)


class PublicationCreateResponse(BaseModel):
    operation_key: str
    state: str
