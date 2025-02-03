# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional
from datetime import datetime


class UserSchema(BaseModel):
    """Base schema for User model."""
    id: int
    created_at: datetime
    email: EmailStr
    is_active: bool = True
    hashed_password: str

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

    model_config = ConfigDict(from_attributes=True)

