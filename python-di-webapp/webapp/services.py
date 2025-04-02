"""Services module."""

from uuid import uuid4
from fastapi import status, Response, HTTPException, UploadFile
from datetime import timedelta
import uuid
from loguru import logger

from .repositories import (
    UserRepository,
    NotFoundError,
    OrderRepository,
    MinioRepository,
    ImageRepository,
    UserNotFoundError,
    OrderNotFoundError
)
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

    def __init__(self, user_repository: UserRepository, minio_repository: MinioRepository, image_repository: ImageRepository) -> None:
        self._repository: UserRepository = user_repository
        self.minio_repository = minio_repository
        self.image_repository = image_repository

    def _resolve_user_image(self, user):
        if getattr(user, "profile_image", None):
            img = self.image_repository.get_image_by_id(user.profile_image)
            if img:
                url = self.minio_repository.get_presigned_url(img.path)
                setattr(user, "profileImage", {"id": img.id, "url": url})
            else:
                setattr(user, "profileImage", None)
        else:
            setattr(user, "profileImage", None)

    def get_users(self) -> list[UserResponse]:
        users = self._repository.get_all()
        for user in users:
            self._resolve_user_image(user)
        return [UserResponse.model_validate(user) for user in users]

    def get_user_by_id(self, user_id: int) -> UserResponse | Response:
        try:
            user = self._repository.get_by_id(user_id)
            if user:
                self._resolve_user_image(user)
                return UserResponse.model_validate(user)
            else:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

    def get_user_by_email(self, email: str):
        user = self._repository.get_by_email(email)
        if user:
            self._resolve_user_image(user)
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
        image_uuid = uuid.uuid4().hex
        file_path = PathHelper.generate_user_profile_path(user_id, image_uuid, file.filename)
        
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type

        object_key = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)
        # 새 이미지 레코드 생성 (bucket 정보는 minio_repository.bucket_name 사용)
        new_image = self.image_repository.add_image(self.minio_repository.bucket_name, object_key)
        # 유저의 프로필 이미지 업데이트 (Image의 id 저장)
        updated_user = self._repository.update_profile_image(user_id, new_image.id)
        self._resolve_user_image(updated_user)
        return UserResponse.model_validate(updated_user)


class OrderService(PresignedUrlResolverMixin):
    def __init__(self, order_repository: OrderRepository, minio_repository: MinioRepository, image_repository: ImageRepository) -> None:
        self._repository: OrderRepository = order_repository
        self.minio_repository = minio_repository
        self.image_repository = image_repository

    def _resolve_order_images(self, order):
        images = []
        if order.order_image_list:
            for image_id in order.order_image_list:
                img = self.image_repository.get_image_by_id(image_id)
                if img:
                    url = self.minio_repository.get_presigned_url(img.path)
                    images.append({"id": img.id, "url": url})
        setattr(order, "orderImageList", images)

    def get_orders(self) -> list[OrderResponse]:
        orders = self._repository.get_all()
        for order in orders:
            self._resolve_order_images(order)
        return [OrderResponse.model_validate(order) for order in orders]

    def get_order_by_id(self, order_id: int) -> OrderResponse | Response:
        try:
            order = self._repository.get_by_id(order_id)
            if order:
                self._resolve_order_images(order)
                return OrderResponse.model_validate(order)
            else:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
        except NotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

    def create_order(self, order_request: OrderRequest) -> OrderResponse:
        order = self._repository.add(order_request)
        return OrderResponse.model_validate(order)

    def delete_order_image(self, order_id: int, image_id: int = None):
        """
        이미지 삭제 시, image_id가 제공되면 해당 이미지만 삭제하고,
        image_id가 없으면 기존의 전체 이미지 삭제(순차 삭제) 함수를 사용합니다.
        """
        try:
            order = self._repository.get_by_id(order_id)
        except OrderNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)

        if image_id is not None:
            # 단일 이미지 삭제: S3에서 파일 삭제 후 DB 연관관계에서 해당 이미지 제거
            img = self.image_repository.get_image_by_id(image_id)
            if img:
                try:
                    self.minio_repository.delete_file(img.path)
                except Exception as e:
                    logger.error(f"Failed to delete file {img.path}: {e}")
            updated_order = self._repository.delete_order_image(order_id, image_id)
        else:
            # image_id 미제공 시 전체 이미지 삭제 방식 사용
            for image_id in order.order_image_list or []:
                img = self.image_repository.get_image_by_id(image_id)
                if img:
                    try:
                        self.minio_repository.delete_file(img.path)
                    except Exception as e:
                        logger.error(f"Failed to delete file {img.path}: {e}")
            updated_order = self._repository.delete_order_image_list(order_id)
        self._resolve_order_images(updated_order)
        return OrderResponse.model_validate(updated_order)

    def upload_order_image(self, order_id: int, file: UploadFile):
        image_uuid = uuid.uuid4().hex
        file_path = PathHelper.generate_order_image_path(order_id, image_uuid, file.filename)
        
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type

        object_key = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)
        # 새 이미지 레코드 생성
        new_image = self.image_repository.add_image(self.minio_repository.bucket_name, object_key)
        # Order의 이미지 id 리스트에 추가
        updated_order = self._repository.add_order_image(order_id, new_image.id)
        self._resolve_order_images(updated_order)
        return OrderResponse.model_validate(updated_order)


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
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
