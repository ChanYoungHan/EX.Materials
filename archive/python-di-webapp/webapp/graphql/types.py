import strawberry
from typing import Optional, List

@strawberry.type
class ImageType:
    id: int
    url: str

@strawberry.type
class UserType:
    id: int
    email: str
    is_active: bool
    profile_image: Optional[ImageType] = None

@strawberry.type
class OrderType:
    id: int
    name: str
    type: str
    quantity: int
    order_image_list: List[ImageType] = strawberry.field(default_factory=list)

@strawberry.type
class DeletionResult:
    success: bool
    message: Optional[str] = None
