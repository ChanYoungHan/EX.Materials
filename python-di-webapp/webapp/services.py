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

    # === User 1번 요구사항: 기존 메서드 수정 ===
    def delete_user_by_id(self, user_id: int) -> Response:
        """사용자 및 연관된 프로필 이미지를 삭제합니다."""
        try:
            user = self._repository.get_by_id(user_id) # 먼저 사용자 정보 조회 (profile_image FK 확인 위해)
            if user and user.profile_image:
                image_id_to_delete = user.profile_image
                # User의 FK를 먼저 NULL로 설정 시도 (선택적, FK 제약조건 회피 목적)
                # self._repository.clear_profile_image_fk(user_id) # 또는 아래에서 이미지 삭제 후 User 삭제

                # 이미지 정보 조회 및 S3 객체 삭제
                image = self.image_repository.get_image_by_id(image_id_to_delete)
                if image:
                    try:
                        self.minio_repository.delete_file(image.path)
                    except Exception as e:
                        logger.error(f"Failed to delete S3 object {image.path} for user {user_id}: {e}")
                        # S3 삭제 실패 시 처리 정책 필요 (예: 로깅 후 계속 진행 또는 에러 반환)

                    # DB에서 이미지 레코드 삭제
                    self.image_repository.delete_image(image_id_to_delete)

            # 사용자 레코드 삭제
            self._repository.delete_by_id(user_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        except UserNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user")

    # === User 2번 요구사항: 신규 메서드 추가 ===
    def delete_profile_image(self, user_id: int) -> UserResponse | Response:
        """사용자의 프로필 이미지를 삭제합니다 (S3 및 DB)."""
        try:
            user = self._repository.get_by_id(user_id)
            if not user:
                raise UserNotFoundError(user_id)

            if not user.profile_image: # 삭제할 프로필 이미지가 없는 경우
                # 이미지가 없으므로 성공으로 간주하고 현재 사용자 정보 반환
                self._resolve_user_image(user) # profileImage 속성 설정
                return UserResponse.model_validate(user)

            image_id_to_delete = user.profile_image
            image = self.image_repository.get_image_by_id(image_id_to_delete)

            # DB에서 User의 profile_image FK를 NULL로 업데이트
            updated_user = self._repository.clear_profile_image_fk(user_id)

            if image: # 이미지 정보가 있으면 S3 객체 삭제 시도
                try:
                    self.minio_repository.delete_file(image.path)
                except Exception as e:
                    logger.error(f"Failed to delete S3 object {image.path} for user {user_id}: {e}")
                    # S3 삭제 실패 시 처리 정책 필요

                # DB에서 이미지 레코드 삭제
                self.image_repository.delete_image(image_id_to_delete)

            # 최종 사용자 정보 (이미지 제거됨) 반환
            self._resolve_user_image(updated_user) # profileImage 속성 설정 (None이 될 것임)
            return UserResponse.model_validate(updated_user)

        except UserNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting profile image for user {user_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete profile image")

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
        if order.images:
            for image in order.images:
                url = self.minio_repository.get_presigned_url(image.path)
                images.append({"id": image.id, "url": url})
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

    def upload_order_image(self, order_id: int, file: UploadFile):
        image_uuid = uuid.uuid4().hex
        file_path = PathHelper.generate_order_image_path(order_id, image_uuid, file.filename)
        
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type

        object_key = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)
        # 새 이미지 레코드 생성 시 order_id를 함께 설정합니다.
        new_image = self.image_repository.add_image(self.minio_repository.bucket_name, object_key, order_id)
        # 추가적인 연관 처리는 필요없이, 새로운 이미지의 FK(order_id)로 인해 역참조 관계(images)에 반영됩니다.
        updated_order = self._repository.get_by_id(order_id)
        self._resolve_order_images(updated_order)
        return OrderResponse.model_validate(updated_order)

    # === Orders 1번 요구사항: 기존 메서드 수정 및 이름 변경 ===
    # 기존: delete_order_image(order_id: int) -> Response: ... return self._repository.delete_by_id(order_id)
    def delete_order_by_id(self, order_id: int) -> Response:
        """주문 및 연관된 모든 이미지를 삭제합니다 (S3 및 DB)."""
        try:
            # DB에서 해당 주문의 모든 이미지 레코드 삭제 및 파일 경로 얻기
            # (주의: Order 객체를 먼저 조회해서 images를 순회하면, Order 삭제 시 FK 제약 발생 가능)
            deleted_image_paths = self.image_repository.delete_images_by_order(order_id)

            # S3에서 관련 이미지 객체들 삭제
            for path in deleted_image_paths:
                try:
                    self.minio_repository.delete_file(path)
                except Exception as e:
                    logger.error(f"Failed to delete S3 object {path} for order {order_id}: {e}")
                    # S3 삭제 실패 시 처리 정책 필요

            # 주문 레코드 삭제
            self._repository.delete_by_id(order_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        except OrderNotFoundError: # delete_by_id에서 발생 가능
             return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting order {order_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete order")

    # === Orders 2번 요구사항: 기존 메서드 유지 (로직 검증 및 Repository 메서드명 변경 반영) ===
    def delete_single_order_image(self, order_id: int, image_id: int) -> OrderResponse | Response:
        """주문에 속한 특정 이미지를 삭제합니다 (S3 및 DB)."""
        try:
            # 이미지 정보 조회 (삭제할 S3 객체 경로 확인 위해)
            image = self.image_repository.get_image_by_id(image_id)
            if not image or image.order_id != order_id: # 이미지가 없거나 해당 주문 소속이 아니면 404
                return Response(status_code=status.HTTP_404_NOT_FOUND)

            image_path = image.path # 경로 저장

            # DB에서 이미지 레코드 삭제 (OrderRepository 메서드 호출)
            # 이 메서드는 Order 객체를 반환하므로 OrderNotFoundError 처리 가능
            updated_order = self._repository.delete_single_image_for_order(order_id, image_id)
            if not updated_order: # delete_single_image_for_order가 None 반환 시 (예외처리 방식에 따라 다름)
                return Response(status_code=status.HTTP_404_NOT_FOUND)

            # S3 객체 삭제
            try:
                self.minio_repository.delete_file(image_path)
            except Exception as e:
                logger.error(f"Failed to delete S3 object {image_path} for order {order_id}, image {image_id}: {e}")
                # S3 삭제 실패 시 처리 정책 필요

            # 최종 주문 정보 (이미지 제거됨) 반환
            self._resolve_order_images(updated_order)
            return OrderResponse.model_validate(updated_order)

        except OrderNotFoundError: # _repository.delete_single_image_for_order 에서 발생 가능
             return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting single image {image_id} for order {order_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete order image")

    # === Orders 3번 요구사항: 기존 메서드 유지 (로직 검증 및 Repository 메서드 의존성 확인) ===
    def delete_all_order_images(self, order_id: int) -> OrderResponse | Response:
        """주문에 속한 모든 이미지를 삭제합니다 (S3 및 DB)."""
        try:
            # DB에서 해당 주문의 모든 이미지 레코드 삭제 및 파일 경로 얻기
            deleted_image_paths = self.image_repository.delete_images_by_order(order_id)

            # S3에서 관련 이미지 객체들 삭제
            for path in deleted_image_paths:
                try:
                    self.minio_repository.delete_file(path)
                except Exception as e:
                    logger.error(f"Failed to delete S3 object {path} for order {order_id}: {e}")
                    # S3 삭제 실패 시 처리 정책 필요

            # 이미지 삭제 후 최종 주문 정보 조회 및 반환
            updated_order = self._repository.get_by_id(order_id) # 이미지 없는 상태로 조회될 것임
            self._resolve_order_images(updated_order)
            return OrderResponse.model_validate(updated_order)

        except OrderNotFoundError:
             return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting all images for order {order_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete all order images")


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
