from typing import List, Optional
from loguru import logger
import strawberry
from strawberry.types import Info

from webapp.services import UserService, OrderService
from .types import UserType, OrderType
from webapp.security import get_password_hash

def get_users_resolver(
    info: Info,
) -> List[UserType]:
    # DI 컨테이너에서 user_service 얻기
    user_service: UserService = info.context["user_service"]
    users = user_service.get_users()
    return [
        UserType(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            profile_image_url=user.profileImageUrl,
        )
        for user in users
    ]

def get_user_by_id_resolver(info: Info, user_id: int) -> Optional[UserType]:
    user_service: UserService = info.context["user_service"]
    user = user_service.get_user_by_id(user_id)
    if not user or isinstance(user, str):  # 404 시 string 혹은 다른 형태로 반환하는 경우
        return None
    return UserType(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        profile_image_url=user.profileImageUrl,
    )

def create_user_resolver(info: Info, email: str, password: str) -> UserType:
    user_service: UserService = info.context["user_service"]
    hashed_pw = get_password_hash(password)

    user = user_service.create_user_with_credential(email, hashed_pw, True, "user")
    return UserType(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
    )

def get_orders_resolver(
    info: Info
) -> List[OrderType]:
    order_service: OrderService = info.context["order_service"]
    orders = order_service.get_orders()
    return [
        OrderType(
            id=order.id,
            name=order.name,
            type=order.type,
            quantity=order.quantity,
            order_image_url_list=order.orderImageUrlList,
        )
        for order in orders
    ]

def create_order_resolver(
    info: Info,
    name: str,
    type: str,
    quantity: int
) -> OrderType:
    order_service: OrderService = info.context["order_service"]
    new_order = order_service.create_order(
        order_request={"name": name, "type": type, "quantity": quantity}
    )
    return OrderType(
        id=new_order.id,
        name=new_order.name,
        type=new_order.type,
        quantity=new_order.quantity,
    )
