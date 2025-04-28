from typing import List, Optional
from strawberry.types import Info

from webapp.services import UserService, OrderService
from .types import UserType, OrderType, DeletionResult
from webapp.utils.security import get_password_hash
from webapp.schemas import OrderRequest

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
            profile_image=user.profileImage,
        )
        for user in users
    ]

def create_user_resolver(info: Info, email: str, password: str) -> UserType:
    user_service: UserService = info.context["user_service"]
    hashed_pw = get_password_hash(password)

    user = user_service.create_user_with_credential(email, hashed_pw, True, "user")
    return UserType(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
    )


def get_user_by_id_resolver(info: Info, user_id: int) -> Optional[UserType]:
    user_service: UserService = info.context["user_service"]
    user = user_service.get_user_by_id(user_id)
    if not user or isinstance(user, str):  # 404 시 string 혹은 다른 형태로 반환하는 경우
        return None
    return UserType(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        profile_image=user.profileImage,
    )

def delete_user_resolver(info: Info, user_id: int) -> UserType:
    user_service: UserService = info.context["user_service"]
    result = user_service.delete_user_by_id(user_id)
    return DeletionResult(
        success=result.status_code == 204,
    )

def delete_profile_image_resolver(info: Info, user_id: int) -> UserType:
    user_service: UserService = info.context["user_service"]
    user = user_service.delete_profile_image(user_id)
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
            order_image_list=order.orderImageList,
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
        order_request=OrderRequest(name=name, type=type, quantity=quantity)
    )
    return OrderType(
        id=new_order.id,
        name=new_order.name,
        type=new_order.type,
        quantity=new_order.quantity,
    )

def get_order_by_id_resolver(info: Info, order_id: int) -> Optional[OrderType]:
    order_service: OrderService = info.context["order_service"]
    order = order_service.get_order_by_id(order_id)
    if not order or isinstance(order, str):
        return None
    return OrderType(
        id=order.id,
        name=order.name,
        type=order.type,
        quantity=order.quantity,
        order_image_list=order.orderImageList,
    )

def delete_order_resolver(info: Info, order_id: int) -> OrderType:
    order_service: OrderService = info.context["order_service"]
    order = order_service.delete_order_by_id(order_id)
    return DeletionResult(
        success=order.status_code == 204,
    )

def delete_single_order_image_resolver(info: Info, order_id: int, image_id: int) -> OrderType:
    order_service: OrderService = info.context["order_service"]
    order = order_service.delete_single_order_image(order_id, image_id)
    return OrderType(
        id=order.id,
        name=order.name,
        type=order.type,
        quantity=order.quantity,
    )

def delete_all_order_images_resolver(info: Info, order_id: int) -> OrderType:
    order_service: OrderService = info.context["order_service"]
    order = order_service.delete_all_order_images(order_id)
    return OrderType(
        id=order.id,
        name=order.name,
        type=order.type,
        quantity=order.quantity,
    )
