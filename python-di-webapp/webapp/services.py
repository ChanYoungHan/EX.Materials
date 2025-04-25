"""Services module."""

import uuid
from uuid import uuid4
from fastapi import status, Response, HTTPException, UploadFile
from datetime import timedelta
from typing import Optional, Dict, List
from loguru import logger

from .repositories import (
    UserRepository,
    NotFoundError,
    OrderRepository,
    MinioRepository,
    ImageRepository,
    MainPageSettingRepository,
    UserNotFoundError,
    OrderNotFoundError
)
from .schemas import UserResponse, OrderResponse, OrderRequest, AuthResponse, ImageSchema, ImageResponse
from .security import verify_password, get_password_hash, decode_access_token, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from .utils import PathHelper

class FileHandlerMixin:
    """
    파일 업로드 및 presigned URL 관련 기능을 제공하는 믹스인 클래스입니다.
    파일 스트림 핸들러 기능을 포함합니다.
    """

    def _resolve_single_presigned_url(
        self, model, path_field: str, url_field: str
    ) -> None:
        file_path = getattr(model, path_field, None)
        if file_path:
            setattr(model, url_field, self.minio_repository.get_presigned_url(file_path))  # type: ignore

    def _resolve_list_presigned_urls(
        self, model, path_field: str, url_field: str
    ) -> None:
        file_paths = getattr(model, path_field, None)
        if file_paths:
            setattr(model, url_field, [self.minio_repository.get_presigned_url(path) for path in file_paths])  # type: ignore

    def _resolve_url(self, path: Optional[str]) -> str:
        """s3 경로를 presigned URL로 변환"""
        return self.minio_repository.get_presigned_url(path) if path else ""  # type: ignore
    

    def _transfrom_image_path_to_url(self, image: ImageSchema) -> ImageResponse:
        """Image 객체를 ImageResponse 스키마로 변환 (path -> URL)"""
        return ImageResponse(
            id=image.id,
            url=self._resolve_url(image.path)
        )

    def handle_file_upload(self, file: UploadFile, path_generator_func, id: int) -> str:
        """
        파일 업로드를 처리하고, 업로드된 파일의 경로를 반환합니다.
        :param minio_repo: 파일 업로드용 minio repository
        :param file: 업로드할 파일 (UploadFile)
        :param path_generator_func: 샘플 경로 생성 함수 (예: PathHelper.generate_category_cover_path)
        :param title: 파일 경로 생성을 위한 제목(예: 카테고리 타이틀)
        :return: 업로드된 파일의 경로 (object key)
        """
        image_id = uuid.uuid4().hex
        file_path = path_generator_func(id, image_id, file.filename or "")
        file_data = file.file
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        content_type = file.content_type
        uploaded_path = self.minio_repository.upload_file(file_data, file_size, content_type, file_path)  # type: ignore
        return uploaded_path

    def upload_and_replace_file(
        self,
        file: UploadFile,
        path_generator_func,
        obj_id: int,
        current_path: Optional[str],
    ) -> str:
        """
        기존의 파일이 존재하면 삭제한 후, 새로운 파일을 업로드합니다.
        """
        if current_path:
            try:
                self.minio_repository.delete_file(current_path)  # type: ignore
            except Exception as e:
                logger.error(f"기존 파일 삭제 실패: {current_path}, {e}")
        return self.handle_file_upload(file, path_generator_func, obj_id)

    def delete_associated_files(self, file_paths: List[str]) -> None:
        """
        객체와 관련된 S3 파일들을 순차적으로 삭제합니다.
        """
        for path in file_paths:
            try:
                self.minio_repository.delete_file(path)  # type: ignore
            except Exception as e:
                logger.error(f"파일 삭제 실패: {path}, {e}")


class UserService(FileHandlerMixin):

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
        """사용자 및 연관된 프로필 이미지를 삭제합니다."""
        try:
            user = self._repository.get_by_id(user_id)

            if user and user.profile_image:
                image_id_to_delete = user.profile_image
                # User의 FK를 먼저 NULL로 설정 시도 (선택적, FK 제약조건 회피 목적)
                self._repository.clear_profile_image_fk(user_id) # 또는 아래에서 이미지 삭제 후 User 삭제

                img = self.image_repository.get_image_by_id(image_id_to_delete)
                if img:
                    self.delete_associated_files([img.path])
                    self.image_repository.delete_image(img.id)
            self._repository.delete_by_id(user_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except UserNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete user")

    def delete_profile_image(self, user_id: int) -> UserResponse | Response:
        """사용자의 프로필 이미지를 삭제합니다 (S3 및 DB)."""
        try:
            user = self._repository.get_by_id(user_id)
            if not user.profile_image:
                self._resolve_user_image(user)
                return UserResponse.model_validate(user)

            img = self.image_repository.get_image_by_id(user.profile_image)
            updated = self._repository.clear_profile_image_fk(user_id)
            if img:
                self.delete_associated_files([img.path])
                self.image_repository.delete_image(img.id)

            self._resolve_user_image(updated)
            return UserResponse.model_validate(updated)
        except UserNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting profile image for user {user_id}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete profile image")

    def upload_profile_image(self, user_id: int, file: UploadFile) -> UserResponse:
        current = None
        try:
            user = self._repository.get_by_id(user_id)
            current = user.profile_image and self.image_repository.get_image_by_id(user.profile_image).path
        except UserNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        object_key = self.upload_and_replace_file(
            file, PathHelper.generate_user_profile_path, user_id, current
        )

        new_img = self.image_repository.add_image(
            self.minio_repository.bucket_name, object_key
        )
        updated = self._repository.update_profile_image(user_id, new_img.id)
        self._resolve_user_image(updated)
        return UserResponse.model_validate(updated)


class OrderService(FileHandlerMixin):
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

    def upload_order_image(self, order_id: int, file: UploadFile) -> OrderResponse:
        object_key = self.handle_file_upload(
            file, PathHelper.generate_order_image_path, order_id
        )
        self.image_repository.add_image(
            self.minio_repository.bucket_name, object_key, order_id
        )
        order = self._repository.get_by_id(order_id)
        self._resolve_order_images(order)
        return OrderResponse.model_validate(order)

    def delete_order_by_id(self, order_id: int) -> Response:
        try:
            paths = self.image_repository.delete_images_by_order(order_id)
            self.delete_associated_files(paths)
            self._repository.delete_by_id(order_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except OrderNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting order {order_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete order")

    def delete_single_order_image(
        self, order_id: int, image_id: int
    ) -> OrderResponse | Response:
        try:
            img = self.image_repository.get_image_by_id(image_id)
            if not img or img.order_id != order_id:
                return Response(status_code=status.HTTP_404_NOT_FOUND)

            updated = self._repository.delete_single_image_for_order(order_id, image_id)
            self.delete_associated_files([img.path])
            self._resolve_order_images(updated)
            return OrderResponse.model_validate(updated)
        except OrderNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting order image {image_id} for {order_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete order image")

    def delete_all_order_images(self, order_id: int) -> OrderResponse | Response:
        try:
            paths = self.image_repository.delete_images_by_order(order_id)
            self.delete_associated_files(paths)
            order = self._repository.get_by_id(order_id)
            self._resolve_order_images(order)
            return OrderResponse.model_validate(order)
        except OrderNotFoundError:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting all images for order {order_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete all order images")


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

class MainPageService(FileHandlerMixin):
    """
    메인 페이지 관련 비즈니스 로직을 처리하는 서비스입니다.
    메인 이미지 및 갤러리 이미지를 관리합니다.
    """
    def __init__(
        self, 
        main_repository: MainPageSettingRepository,
        minio_repository: MinioRepository,
        image_repository: ImageRepository
    ):
        self._repository = main_repository
        self.minio_repository = minio_repository
        self.image_repository = image_repository
        
    # --- 메인 이미지 관리 ---
    def set_main_image(self, file: UploadFile) -> ImageResponse:
        """메인 이미지를 설정합니다."""
        try:
            object_key = self.handle_file_upload(
                file, PathHelper.generate_main_image_path, 0
            )
            
            # 이미지 메타데이터 저장
            new_image = self.image_repository.add_image(
                self.minio_repository.bucket_name, object_key
            )
            
            # 랜딩 페이지 설정에 메인 이미지 ID 저장
            self._repository.upsert_setting('main_image_id', new_image.id)
            
            # 이미지 정보 반환
            return self._transfrom_image_path_to_url(new_image)
            
        except Exception as e:
            logger.error(f"Failed to set main image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to set main image"
            )
    
    def delete_main_image(self) -> None:
        """메인 이미지를 삭제합니다."""
        try:
            # 현재 메인 이미지 ID 조회
            image_id = self._repository.get_setting('main_image_id')
            
            if image_id:
                # 이미지 정보 조회
                image = self.image_repository.get_image_by_id(image_id)
                if image:
                    # MinIO에서 파일 삭제
                    try:
                        self.minio_repository.delete_file(image.path)
                    except Exception as e:
                        logger.error(f"Failed to delete file from MinIO: {e}")
                    
                    # DB에서 이미지 레코드 삭제
                    self.image_repository.delete_image(image_id)
            
            # 설정에서 메인 이미지 ID 삭제
            self._repository.delete_setting('main_image_id')
            
        except Exception as e:
            logger.error(f"Failed to delete main image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete main image"
            )
    
    def get_main_image(self) -> Optional[ImageResponse]:
        """현재 메인 이미지 정보를 조회합니다."""
        try:
            image_id = self._repository.get_setting('main_image_id')
            if not image_id:
                return None
            image = self.image_repository.get_image_by_id(image_id)
            if not image:
                return None
            return self._transfrom_image_path_to_url(image)
            
        except Exception as e:
            logger.error(f"Failed to get main image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get main image"
            )
    
    # --- 갤러리 이미지 관리 ---
    def add_gallery_image(self, file: UploadFile) -> List[ImageResponse]:
        """갤러리에 이미지를 추가합니다."""
        try:
            object_key = self.handle_file_upload(
                file, PathHelper.generate_gallery_image_path, 0
            )
            
            # 이미지 메타데이터 저장
            new_image = self.image_repository.add_image(
                self.minio_repository.bucket_name, object_key
            )
            
            # 현재 갤러리 이미지 ID 목록 조회
            gallery_ids = self._repository.get_setting('gallery_image_ids')
            if gallery_ids is None:
                gallery_ids = []
            elif not isinstance(gallery_ids, list):
                gallery_ids = []
            
            # 새 이미지 ID 추가
            gallery_ids.append(new_image.id)
            
            # 갤러리 이미지 ID 목록 업데이트
            self._repository.upsert_setting('gallery_image_ids', gallery_ids)
            
            # 전체 갤러리 이미지 정보 반환
            return [self._transfrom_image_path_to_url(self.image_repository.get_image_by_id(image_id)) for image_id in gallery_ids]
            
        except Exception as e:
            logger.error(f"Failed to add gallery image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add gallery image"
            )
    
    def delete_gallery_image(self, image_id: int) -> None:
        """갤러리에서 이미지를 삭제합니다."""
        try:
            # 현재 갤러리 이미지 ID 목록 조회
            gallery_ids = self._repository.get_setting('gallery_image_ids')
            
            if not gallery_ids or not isinstance(gallery_ids, list):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Gallery is empty or not found"
                )
            
            # 이미지 ID가 갤러리에 있는지 확인
            if image_id not in gallery_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Image not found in gallery"
                )
            
            # 이미지 정보 조회
            image = self.image_repository.get_image_by_id(image_id)
            if image:
                # MinIO에서 파일 삭제
                try:
                    self.minio_repository.delete_file(image.path)
                except Exception as e:
                    logger.error(f"Failed to delete file from MinIO: {e}")
                
                # DB에서 이미지 레코드 삭제
                self.image_repository.delete_image(image_id)
            
            # 갤러리 이미지 ID 목록에서 제거
            gallery_ids.remove(image_id)
            
            # 갤러리 이미지 ID 목록 업데이트
            self._repository.upsert_setting('gallery_image_ids', gallery_ids)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete gallery image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete gallery image"
            )
    
    def get_gallery_images(self) -> List[ImageResponse]:
        """현재 갤러리 이미지 목록을 조회합니다."""
        try:
            gallery_ids = self._repository.get_setting('gallery_image_ids')
            if not gallery_ids or not isinstance(gallery_ids, list):
                return []
                
            return [self._transfrom_image_path_to_url(self.image_repository.get_image_by_id(image_id)) for image_id in gallery_ids]
            
        except Exception as e:
            logger.error(f"Failed to get gallery images: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get gallery images"
            )