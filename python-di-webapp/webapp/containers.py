"""Containers module."""

from dependency_injector import containers, providers
from .database import Database
from .repositories import UserRepository, OrderRepository, MinioRepository, ImageRepository
from .services import UserService, OrderService, AuthService
from minio import Minio
from .logger_config import configure_logger

def init_minio_client(endpoint: str, access_key: str, secret_key: str, secure: bool) -> Minio:
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

class Container(containers.DeclarativeContainer):

    wiring_config = containers.WiringConfiguration(modules=[".endpoints"])

    config = providers.Configuration()
    config.from_yaml("config.yml")

    db = providers.Singleton(Database, db_url=config.db.url)

    user_repository = providers.Factory(
        UserRepository,
        session_factory=db.provided.session,
    )

    order_repository = providers.Factory(
        OrderRepository,
        session_factory=db.provided.session,
    )

    # ImageRepository 제공자 추가
    image_repository = providers.Factory(
        ImageRepository,
        session_factory=db.provided.session,
    )

    # MinIO 클라이언트를 Resource로 생성하여 MinioRepository에 전달
    minio_client = providers.Resource(
        init_minio_client,
        endpoint=config.minio.endpoint,
        access_key=config.minio.access_key,
        secret_key=config.minio.secret_key,
        secure=config.minio.secure,
    )

    minio_repository = providers.Singleton(
        MinioRepository,
        minio_client=minio_client,
        bucket_name=config.minio.bucket_name,
    )

    user_service = providers.Factory(
        UserService,
        user_repository=user_repository,
        minio_repository=minio_repository,
        image_repository=image_repository,
    )

    # OrderService에도 image_repository 의존성을 추가
    order_service = providers.Factory(
        OrderService,
        order_repository=order_repository,
        minio_repository=minio_repository,
        image_repository=image_repository,
    )

    auth_service = providers.Factory(
        AuthService,
        user_repository=user_repository,
    )
