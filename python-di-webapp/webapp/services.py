"""Services module."""

from uuid import uuid4
from fastapi import status, Response, HTTPException, UploadFile
from datetime import timedelta
import uuid
from loguru import logger

from .repositories import UserRepository, NotFoundError, OrderRepository, MinioRepository
from .schemas import UserResponse, OrderResponse, OrderRequest, AuthResponse
from .security import verify_password, get_password_hash, decode_access_token, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from .utils import PathHelper, TableType

class PresignedUrlResolverMixin:
    """
    공통 presigned URL 변환 로직을 제공하는 믹스인 클래스입니다.
    단일 파일 경로 또는 경로 리스트를 presigned URL로 변환하는 헬퍼 메서드를 포함합니다.
    """
    def _resolve_single_presigned_url(self, model, path_field: str, url_field: str) -> None:
        file_path = getattr(model, path_field, None)
        if file_path:
            setattr(model, url_field, self.minio_repository.get_presigned_url(file_path))

    def _resolve_list_presigned_urls(self, model, path_field: str, url_field: str) -> None:
        file_paths = getattr(model, path_field, None)
        if file_paths:
            setattr(model, url_field, [self.minio_repository.get_presigned_url(path) for path in file_paths])

class UserService(PresignedUrlResolverMixin):

    def __init__(self, user_repository: UserRepository, minio_repository: MinioRepository) -> None:
        self._repository: UserRepository = user_repository
        self.minio_repository = minio_repository

    def get_users(self) -> list[UserResponse]:
        users = self._repository.get_all()
        for user in users:
            self._resolve_single_presigned_url(user, 'profile_image_path', 'profile_image_url')
        return [UserResponse.model_validate(user) for user in users]

    def get_user_by_id(self, user_id: int) -> UserResponse | Response:
        try:
            user = self._repository.get_by_id(user_id)
            if user:
                self._resolve_single_presigned_url(user, 'profile_image_path', 'profile_image_url')
                return UserResponse.model_validate(user)
            else:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

    def get_user_by_email(self, email: str):
        user = self._repository.get_by_email(email)
        if user:
            self._resolve_single_presigned_url(user, 'profile_image_path', 'profile_image_url')
        return user

    def create_user(self) -> UserResponse:
        uid = uuid4()
        user = self._repository.add(email=f"{uid}@email.com", password="pwd", is_active=True, role="user")
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

    def upload_profile_image(self, user_id: int, file: UploadFile):
        image_id = uuid.uuid4().hex
        file_path = PathHelper.generate_user_profile_path(user_id, image_id, file.filename)
        
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type

        object_key = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)
        updated_user = self._repository.update_profile_image(user_id, object_key)
        self._resolve_single_presigned_url(updated_user, 'profile_image_path', 'profile_image_url')
        return UserResponse.model_validate(updated_user)


class OrderService(PresignedUrlResolverMixin):
    def __init__(self, order_repository: OrderRepository, minio_repository: MinioRepository) -> None:
        self._repository: OrderRepository = order_repository
        self.minio_repository = minio_repository

    def get_orders(self) -> list[OrderResponse]:
        orders = self._repository.get_all()
        for order in orders:
            self._resolve_list_presigned_urls(order, 'order_image_path_list', 'order_image_url_list')
        return [OrderResponse.model_validate(order) for order in orders]

    def get_order_by_id(self, order_id: int) -> OrderResponse | Response:
        try:
            order = self._repository.get_by_id(order_id)
            if order:
                self._resolve_list_presigned_urls(order, 'order_image_path_list', 'order_image_url_list')
                return OrderResponse.model_validate(order)
            else:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
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

    def upload_order_image(self, order_id: int, file: UploadFile):
        image_id = uuid.uuid4().hex
        file_path = PathHelper.generate_order_image_path(order_id, image_id, file.filename)
        
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type

        object_key = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)
        updated_order = self._repository.add_order_image_path(order_id, object_key)
        self._resolve_list_presigned_urls(updated_order, 'order_image_path_list', 'order_image_url_list')
        return OrderResponse.model_validate(updated_order)

    def delete_order_image_path_list(self, order_id: int) -> OrderResponse:
        # 기존 이미지 경로 목록 가져오기
        order = self._repository.get_by_id(order_id)
        image_paths = order.order_image_path_list or []
        
        # S3에서 이미지 파일들 삭제
        for image_path in image_paths:
            try:
                self.minio_repository.delete_file(image_path)
            except ValueError as e:
                logger.error(f"Failed to delete file {image_path}: {str(e)}")
                
        # DB에서 이미지 경로 목록 삭제
        updated_order = self._repository.delete_order_image_path_list(order_id)
        return OrderResponse.model_validate(updated_order)


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
