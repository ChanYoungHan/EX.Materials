"""Containers module."""

from dependency_injector import containers, providers
from .database import Database
from .repositories import (
    UserRepository, OrderRepository, MinioRepository, 
    ImageRepository, MainPageSettingRepository, DocumentRepository
)
from .services import (
    UserService, OrderService, AuthService, 
    MainPageService, TestNoSQLService
)
from .resources import init_mongodb_db
from minio import Minio
import os
from pathlib import Path
from .core.crypto import RSACrypto

def init_minio_client(endpoint: str, access_key: str, secret_key: str, secure: bool) -> Minio:
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

class Container(containers.DeclarativeContainer):

    wiring_config = containers.WiringConfiguration(modules=[".endpoints", ".graphql.resolvers"])

    config = providers.Configuration()
    
    # 환경 변수에서 설정 파일 경로를 가져옴
    config_path = os.environ.get('CONFIG_PATH', 'config.yml')
    config.from_yaml(config_path)
    
    # SQL Database client
    db = providers.Singleton(Database, db_url=config.db.url)

    # MongoDB Resource - 컬렉션 접근자 함수 사용
    mongodb_db = providers.Resource(
        init_mongodb_db,
        mongodb_uri=config.mongodb.uri,
        database=config.mongodb.db_name,
    )

    crypto = providers.Singleton(
        RSACrypto,
        private_key_path=os.path.join(
            Path(__file__).parent.parent,  # 프로젝트 루트            
            config.owner_auth.keys_dir(),  # 설정에서 키 디렉토리 가져오기
            config.owner_auth.private_key_filename()  # 설정에서 비밀키 파일 이름 가져오기
        ),
        public_key_path=os.path.join(
            Path(__file__).parent.parent,  # 프로젝트 루트
            config.owner_auth.keys_dir(),  # 설정에서 키 디렉토리 가져오기
            config.owner_auth.public_key_filename()  # 설정에서 공개키 파일 이름 가져오기
        ),
        log_owner_email=config.owner_auth.log_owner_email
    )

    # crypto/owner_auth 관련 설정 DI
    
    owner_auth_header_name = providers.Callable(
        config.owner_auth.owner_header_name
    )
    owner_auth_protected_paths = providers.Callable(
        config.owner_auth.protected_paths
    )

    # SQL Repositories
    user_repository = providers.Factory(
        UserRepository,
        session_factory=db.provided.session,
    )

    order_repository = providers.Factory(
        OrderRepository,
        session_factory=db.provided.session,
    )

    image_repository = providers.Factory(
        ImageRepository,
        session_factory=db.provided.session,
    )

    main_page_repository = providers.Factory(
        MainPageSettingRepository,
        session_factory=db.provided.session,
    )

    # NoSQL Repository - 개선된 접근법
    test_document_repository = providers.Factory(
        DocumentRepository,
        get_collection=mongodb_db,
        collection_name="test_documents",
    )
    
    # 다른 컬렉션에 접근하는 리포지토리 추가 예시
    user_document_repository = providers.Factory(
        DocumentRepository,
        get_collection=mongodb_db,
        collection_name="users",
    )

    # MinIO client
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

    # Services
    user_service = providers.Factory(
        UserService,
        user_repository=user_repository,
        minio_repository=minio_repository,
        image_repository=image_repository,
    )

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

    main_page_service = providers.Factory(
        MainPageService,
        main_repository=main_page_repository,
        minio_repository=minio_repository,
        image_repository=image_repository,
    )

    # NoSQL Service - 개선된 접근법
    nosql_service = providers.Factory(
        TestNoSQLService,
        document_repository=test_document_repository,
    )

