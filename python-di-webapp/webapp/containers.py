"""Containers module."""

from dependency_injector import containers, providers

from .database import Database
from .repositories import UserRepository, OrderRepository
from .services import UserService, OrderService, AuthService


class Container(containers.DeclarativeContainer):

    wiring_config = containers.WiringConfiguration(modules=[".endpoints"])

    config = providers.Configuration()
    config.from_yaml("config.yml")


    db = providers.Singleton(Database, db_url=config.db.url)

    user_repository = providers.Factory(
        UserRepository,
        session_factory=db.provided.session,
    )

    user_service = providers.Factory(
        UserService,
        user_repository=user_repository,
    )

    order_repository = providers.Factory(
        OrderRepository,
        session_factory=db.provided.session,
    )

    order_service = providers.Factory(
        OrderService,
        order_repository=order_repository,
    )

    auth_service = providers.Factory(
        AuthService,
        user_repository=user_repository,
    )
