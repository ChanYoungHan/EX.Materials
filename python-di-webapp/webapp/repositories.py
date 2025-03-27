import asyncio

from contextlib import AbstractContextManager
from typing import Callable, Iterator, BinaryIO, List
from datetime import timedelta

from sqlalchemy.orm import Session
from minio import Minio
from minio.error import S3Error

from .models import User, Order
from .schemas import OrderRequest

class UserRepository:

    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def get_all(self) -> Iterator[User]:
        with self.session_factory() as session:
            return session.query(User).all()

    def get_by_id(self, user_id: int) -> User:
        with self.session_factory() as session:
            user = session.query(User).filter(User.id == user_id).scalar()
            if not user:
                raise UserNotFoundError(user_id)
            return user

    def get_by_email(self, email: str) -> User:
        with self.session_factory() as session:
            return session.query(User).filter(User.email == email).first()

    def add(self, email: str, password: str, is_active: bool, role: str = "user") -> User:
        with self.session_factory() as session:
            user = User(email=email, hashed_password=password, is_active=is_active, role=role)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def delete_by_id(self, user_id: int) -> None:
        with self.session_factory() as session:
            entity: User = session.query(User).filter(User.id == user_id).first()
            if not entity:
                raise UserNotFoundError(user_id)
            session.delete(entity)
            session.commit()

    def update_profile_image(self, user_id: int, image_path: str) -> User:
        # DB에 S3 객체의 key(파일 경로)를 저장합니다.
        with self.session_factory() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                raise UserNotFoundError(user_id)
            user.profile_image_path = image_path
            session.commit()
            session.refresh(user)
            return user

class OrderRepository:
    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def get_all(self) -> Iterator[Order]:
        with self.session_factory() as session:
            return session.query(Order).all()

    def get_by_id(self, order_id: int) -> Order:
        with self.session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).scalar()
            if not order:
                raise OrderNotFoundError(order_id)
            return order

    def add(self, order_request: OrderRequest) -> Order:
        with self.session_factory() as session:
            order = Order(**order_request.model_dump())
            session.add(order)
            session.commit()
            session.refresh(order)
            return order

    def delete_by_id(self, order_id: int) -> None:
        with self.session_factory() as session:
            entity: Order = session.query(Order).filter(Order.id == order_id).first()
            if not entity:
                raise OrderNotFoundError(order_id)
            session.delete(entity)
            session.commit()

    def add_order_image_path(self, order_id: int, image_path: str) -> Order:
        # Order의 이미지 경로 리스트에 S3의 파일 경로(object key)를 추가합니다.
        from loguru import logger
        with self.session_factory() as session:
            logger.debug(f"add_order_image_path: {order_id}, {image_path}")
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                raise OrderNotFoundError(order_id)
            if order.order_image_path_list is None:
                order.order_image_path_list = []
            order.order_image_path_list.append(image_path)
            logger.debug(f"order.order_image_path_list: {order.order_image_path_list}")
            session.commit()
            session.refresh(order)
            return order

    def delete_order_image_path_list(self, order_id: int) -> Order:
        # Order의 이미지 경로 리스트를 삭제합니다.
        with self.session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                raise OrderNotFoundError(order_id)
            order.order_image_path_list = []
            session.commit()
            session.refresh(order)
            return order

class NotFoundError(Exception):
    entity_name: str

    def __init__(self, entity_id):
        super().__init__(f"{self.entity_name} not found, id: {entity_id}")

class UserNotFoundError(NotFoundError):
    entity_name: str = "User"

class OrderNotFoundError(NotFoundError):
    entity_name: str = "Order"

class MinioRepository:
    def __init__(self, minio_client: Minio, bucket_name: str = "socialing") -> None:
        self.client = minio_client
        self.bucket_name = bucket_name

        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def list_objects(self, table_type: str, table_id: int) -> List[str]:
        prefix = f"{table_type}/{table_id}/"
        objects = self.client.list_objects(self.bucket_name, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]

    def get_presigned_url(self, object_key: str, expires: timedelta = timedelta(days=1)) -> str:
        try:
            stat = self.client.stat_object(self.bucket_name, object_key)
            content_type = stat.content_type
            response_headers = {'response-content-type': content_type}
            return self.client.presigned_get_object(
                self.bucket_name,
                object_key,
                expires=expires,
                response_headers=response_headers
            )
        except S3Error as e:
            raise ValueError(f"Failed to generate presigned URL: {str(e)}")

    def upload_file(self, file_data: BinaryIO, file_size: int, content_type: str, object_key: str) -> str:
        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_key,
                data=file_data,
                length=file_size,
                content_type=content_type
            )
            return object_key
        except S3Error as e:
            raise ValueError(f"Failed to upload file: {str(e)}")

    def delete_file(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket_name, object_key)
        except S3Error as e:
            raise ValueError(f"Failed to delete file: {str(e)}")
