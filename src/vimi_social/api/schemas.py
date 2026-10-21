from pydantic import BaseModel, Field


class PublicationRequest(BaseModel):
    operation_key: str = Field(min_length=8, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)


class PublicationResponse(BaseModel):
    operation_key: str
    state: str
    joined_existing_reservation: bool
