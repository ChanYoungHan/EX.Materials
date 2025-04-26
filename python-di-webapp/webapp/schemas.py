# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import List, Union, Optional, Dict, Any
from datetime import datetime


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


# NoSQL 스키마 추가
class TestDocumentBase(BaseModel):
    """Base schema for test documents."""
    name: str = Field(..., description="문서의 이름")
    content: Dict[str, Any] = Field(default_factory=dict, description="문서의 컨텐츠")
    tags: List[str] = Field(default_factory=list, description="문서와 관련된 태그")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "테스트 문서",
                "content": {
                    "key1": "value1",
                    "key2": 42,
                    "nested": {
                        "nestedKey": "nestedValue"
                    }
                },
                "tags": ["테스트", "예시", "nosql"]
            }
        }
    )

class TestDocumentCreate(TestDocumentBase):
    """Schema for creating a new test document."""
    pass

class TestDocumentUpdate(BaseModel):
    """Schema for updating an existing test document."""
    name: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "업데이트된 문서",
                "content": {
                    "key1": "업데이트된 값",
                    "key3": "새로운 값"
                },
                "tags": ["업데이트", "nosql"]
            }
        }
    )

class TestDocumentResponse(TestDocumentBase):
    """Schema for representing a test document in responses."""
    id: str = Field(..., alias="_id", description="문서 ID")
    created_at: Optional[datetime] = Field(None, description="문서 생성 시간")
    updated_at: Optional[datetime] = Field(None, description="문서 마지막 업데이트 시간")
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "_id": "60d21b4667d0d8992e610c85",
                "name": "테스트 문서",
                "content": {
                    "key1": "value1",
                    "key2": 42
                },
                "tags": ["테스트", "예시"],
                "created_at": "2023-07-01T12:00:00Z",
                "updated_at": "2023-07-01T13:30:00Z"
            }
        }
    )
