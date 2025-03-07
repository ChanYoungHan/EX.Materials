# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import List, Union


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
    profileImageUrl: Union[str, None] = Field(default=None, alias="profile_image_url")

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
    orderImageUrlList: List[str] = Field(default_factory=list, alias="order_image_url_list")
    
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AuthResponse(BaseModel):
    """Response schema for authentication."""
    access_token: str
    token_type: str
    user: UserResponse

