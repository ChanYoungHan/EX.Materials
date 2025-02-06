"""Services module."""

from uuid import uuid4
from typing import Iterator, Tuple
from fastapi import status, Response

from .repositories import UserRepository, NotFoundError, OrderRepository
from .schemas import UserResponse, OrderResponse, OrderRequest


class UserService:

    def __init__(self, user_repository: UserRepository) -> None:
        self._repository: UserRepository = user_repository

    def get_users(self) -> list[UserResponse]:
        users = self._repository.get_all()
        return [UserResponse.model_validate(user) for user in users]

    def get_user_by_id(self, user_id: int) -> UserResponse | Response:
        try:
            user = self._repository.get_by_id(user_id)            
            return UserResponse.model_validate(user) if user is not None else Response(status_code=status.HTTP_404_NOT_FOUND)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

    def create_user(self) -> UserResponse:
        uid = uuid4()
        user = self._repository.add(email=f"{uid}@email.com", password="pwd")
        return UserResponse.model_validate(user)

    def delete_user_by_id(self, user_id: int) -> Response:
        try:
            self._repository.delete_by_id(user_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)


class OrderService:
    def __init__(self, order_repository: OrderRepository) -> None:
        self._repository: OrderRepository = order_repository

    def get_orders(self) -> list[OrderResponse]:
        orders = self._repository.get_all()
        return [OrderResponse.model_validate(order) for order in orders]

    def get_order_by_id(self, order_id: int) -> OrderResponse | Response:
        try:
            order = self._repository.get_by_id(order_id)
            return OrderResponse.model_validate(order) if order is not None else Response(status_code=status.HTTP_404_NOT_FOUND)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

    def create_order(self, order_request: OrderRequest) -> OrderResponse:
        order = self._repository.add(name=order_request.name, type=order_request.type)
        return OrderResponse.model_validate(order)

    def delete_order_by_id(self, order_id: int) -> Response:
        try:
            self._repository.delete_by_id(order_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
