"""Application module."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .containers import Container
from . import endpoints
from .utils.logger_config import configure_logger
from .graphql.schema import graphql_app
from .middleware.owner import OwnerMiddleware

def create_app() -> FastAPI:
    container = Container()
    container.init_resources()

    configure_logger()

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # crypto 인스턴스 생성 시도
    try:
        crypto = container.crypto()
        # 키가 정상적으로 로드된 경우에만 미들웨어 등록
        app.add_middleware(
            OwnerMiddleware,
            crypto=crypto,
            header_name=container.owner_auth_header_name(),
            protected_paths=container.owner_auth_protected_paths(),
        )
        logger.info("[OwnerAuth] 미들웨어가 정상적으로 등록되었습니다.")
    except FileNotFoundError:
        logger.warning("[OwnerAuth] 키 파일이 없어 미들웨어를 등록하지 않습니다.")

    app.container = container
    app.include_router(endpoints.test_router) #TODELETE : 테스트용 엔드포인트
    app.include_router(endpoints.user_router)
    app.include_router(endpoints.order_router)
    app.include_router(endpoints.auth_router)
    app.include_router(endpoints.main_page_router)
    app.include_router(endpoints.main_page_admin_router)
    app.include_router(endpoints.nosql_router)  # NoSQL 라우터 추가
    app.include_router(graphql_app, prefix="/graphql")


    @app.get("/status")
    def get_status():
        return {"status": "OK"}

    return app


app = create_app()
