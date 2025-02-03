"""Services module."""

from uuid import uuid4
from typing import Iterator, Tuple
from fastapi import status

from .repositories import UserRepository, NotFoundError
from .models import User


class UserService:

    def __init__(self, user_repository: UserRepository) -> None:
        self._repository: UserRepository = user_repository

    def get_users(self) -> Iterator[User]:
        return self._repository.get_all()

    def get_user_by_id(self, user_id: int) -> Tuple[User, int]:
        try:
            user = self._repository.get_by_id(user_id)
            return user, status.HTTP_200_OK
        except NotFoundError:
            return None, status.HTTP_404_NOT_FOUND

    def create_user(self) -> Tuple[User, int]:
        uid = uuid4()
        user = self._repository.add(email=f"{uid}@email.com", password="pwd")
        return user, status.HTTP_201_CREATED

    def delete_user_by_id(self, user_id: int) -> int:
        try:
            self._repository.delete_by_id(user_id)
            return status.HTTP_204_NO_CONTENT
        except NotFoundError:
            return status.HTTP_404_NOT_FOUND
