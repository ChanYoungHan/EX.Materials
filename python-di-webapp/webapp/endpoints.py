"""Endpoints module."""

from fastapi import APIRouter, Depends, Response, status
from dependency_injector.wiring import inject, Provide

from .containers import Container
from .services import UserService
from .schemas import UserResponse
router = APIRouter()


@router.get("/users", response_model=list[UserResponse])
@inject
def get_list(
        user_service: UserService = Depends(Provide[Container.user_service]),
) -> list[UserResponse]:
    return user_service.get_users()


@router.get("/users/{user_id}", response_model=UserResponse)
@inject
def get_by_id(
        user_id: int,
        user_service: UserService = Depends(Provide[Container.user_service]),
) -> UserResponse | Response:
    return user_service.get_user_by_id(user_id)


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
@inject
def add(
        user_service: UserService = Depends(Provide[Container.user_service]),
) -> UserResponse:
    return user_service.create_user()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
def remove(
        user_id: int,
        user_service: UserService = Depends(Provide[Container.user_service]),
) -> Response:
    return user_service.delete_user_by_id(user_id)


@router.get("/status")
def get_status():
    return {"status": "OK"}
