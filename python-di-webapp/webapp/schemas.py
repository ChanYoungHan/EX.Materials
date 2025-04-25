# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import List, Optional


class ImageSchema(BaseModel):
    id: int
    path: str

    model_config = ConfigDict(from_attributes=True)

class ImageResponse(BaseModel):
    id: int
    url: str

    model_config = ConfigDict(from_attributes=True)


class UserRequest(BaseModel):
    """Request schema for User creation."""
    email: EmailStr
    is_active: bool = True
    password: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """Response schema for User model."""
    id: int
    email: EmailStr
    is_active: bool = True
    # profileImage는 ImageResponse 객체 (단일 이미지)로 반환
    profileImage: Optional[ImageResponse] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderRequest(BaseModel):
    name: str
    type: str
    quantity: int


class OrderResponse(BaseModel):
    id: int
    name: str
    type: str
    quantity: int
    # orderImageList는 ImageResponse 객체들의 리스트로 반환
    orderImageList: List[ImageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AuthResponse(BaseModel):
    """Response schema for authentication."""
    access_token: str
    token_type: str
    user: UserResponse

