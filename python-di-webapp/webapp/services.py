"""Services module."""

from uuid import uuid4
from fastapi import status, Response, HTTPException
from datetime import timedelta

from .repositories import UserRepository, NotFoundError, OrderRepository
from .schemas import UserResponse, OrderResponse, OrderRequest, AuthResponse
from .security import verify_password, get_password_hash, decode_access_token, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES


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

    def get_user_by_email(self, email: str):
        return self._repository.get_by_email(email)

    def create_user(self) -> UserResponse:
        uid = uuid4()
        user = self._repository.add(email=f"{uid}@email.com", password="pwd")
        return UserResponse.model_validate(user)

    def create_user_with_credential(self, email: str, hashed_password: str, is_active: bool, role: str):
        user = self._repository.add(email=email, password=hashed_password, is_active=is_active, role=role)
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
        order = self._repository.add(order_request)
        return OrderResponse.model_validate(order)

    def delete_order_by_id(self, order_id: int) -> Response:
        try:
            self._repository.delete_by_id(order_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)


class AuthService:
    def __init__(self, user_repository) -> None:
        self._user_repository = user_repository

    def signup(self, user_req) -> dict:
        existing_user = self._user_repository.get_by_email(user_req.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="해당 이메일로 가입된 사용자가 이미 존재합니다."
            )
        hashed_pw = get_password_hash(user_req.password)
        new_user = self._user_repository.add(
            email=user_req.email,
            password=hashed_pw,
            is_active=user_req.is_active,
            role="user"
        )
        return new_user

    def login(self, username: str, password: str) -> AuthResponse:
        user = self._user_repository.get_by_email(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 올바르지 않습니다.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        access_token = create_access_token(
            data={"sub": user.email, "role": user.role},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        return AuthResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )

    def get_current_user(self, token: str):
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 토큰입니다.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="토큰 정보에 이메일이 없습니다."
            )
        user = self._user_repository.get_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="해당 유저가 존재하지 않습니다."
            )
        return user

    def require_admin(self, user):
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자 권한이 없습니다."
            )
        return user
