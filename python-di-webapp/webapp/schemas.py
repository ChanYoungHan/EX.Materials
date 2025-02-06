# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional
from datetime import datetime


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

    model_config = ConfigDict(from_attributes=True)


class OrderRequest(BaseModel):
    name: str
    type: str


class OrderResponse(BaseModel):
    id: int
    name: str
    type: str

    model_config = ConfigDict(from_attributes=True)

