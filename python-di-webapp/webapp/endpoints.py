"""Endpoints module."""

from fastapi import APIRouter, Depends, Response, status
from dependency_injector.wiring import inject, Provide

from .containers import Container
from .services import UserService, OrderService
from .schemas import UserResponse, OrderResponse, OrderRequest

user_router = APIRouter(prefix="/users", tags=["users"])
order_router = APIRouter(prefix="/orders", tags=["orders"])

@inject
def get_user_service(
    user_service: UserService = Depends(Provide[Container.user_service])
) -> UserService:
    return user_service

@inject
def get_order_service(
    order_service: OrderService = Depends(Provide[Container.order_service])
) -> OrderService:
    return order_service

########################################################
# USER
########################################################
@user_router.get("", response_model=list[UserResponse])
def get_list(
        user_service: UserService = Depends(get_user_service),
) -> list[UserResponse]:
    return user_service.get_users()


@user_router.get("/{user_id}", response_model=UserResponse)
def get_by_id(
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> UserResponse | Response:
    return user_service.get_user_by_id(user_id)


@user_router.post("", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def add(
        user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    return user_service.create_user()


@user_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> Response:
    return user_service.delete_user_by_id(user_id)


########################################################
# ORDER
########################################################

@order_router.get("", response_model=list[OrderResponse])
def get_orders(order_service: OrderService = Depends(get_order_service)) -> list[OrderResponse]:
    return order_service.get_orders()

@order_router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, order_service: OrderService = Depends(get_order_service)) -> OrderResponse | Response:
    return order_service.get_order_by_id(order_id)

@order_router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def add_order(order_request: OrderRequest, order_service: OrderService = Depends(get_order_service)) -> OrderResponse:
    return order_service.create_order(order_request)

@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_order(order_id: int, order_service: OrderService = Depends(get_order_service)) -> Response:
    return order_service.delete_order_by_id(order_id)
