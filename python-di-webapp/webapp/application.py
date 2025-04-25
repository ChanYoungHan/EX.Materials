"""Application module."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .containers import Container
from . import endpoints
from .logger_config import configure_logger
from .graphql.schema import graphql_app

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

    app.container = container
    app.include_router(endpoints.test_router) #TODELETE : 테스트용 엔드포인트
    app.include_router(endpoints.user_router)
    app.include_router(endpoints.order_router)
    app.include_router(endpoints.auth_router)
    app.include_router(endpoints.main_page_admin_router)
    app.include_router(endpoints.main_page_router)
    app.include_router(graphql_app, prefix="/graphql")


    @app.get("/status")
    def get_status():
        return {"status": "OK"}

    return app


app = create_app()
