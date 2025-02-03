"""Services module."""

from uuid import uuid4
from typing import Iterator, Tuple
from fastapi import status, Response

from .repositories import UserRepository, NotFoundError
from .models import User
from .schemas import UserResponse


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
