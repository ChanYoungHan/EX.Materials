import strawberry
from typing import Optional, List

@strawberry.type
class UserType:
    id: int
    email: str
    is_active: bool
    profile_image_url: Optional[str] = None

@strawberry.type
class OrderType:
    id: int
    name: str
    type: str
    quantity: int
    order_image_url_list: List[str] = strawberry.field(default_factory=list)
