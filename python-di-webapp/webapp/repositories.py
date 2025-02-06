"""
Repositories module.
Repository returns should be schemas. Because it can't used after commit.
"""


from contextlib import AbstractContextManager
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from .models import User, Order


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
    

    def add(self, email: str, password: str, is_active: bool = True) -> User:
        with self.session_factory() as session:
            user = User(email=email, hashed_password=password, is_active=is_active)
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

    def add(self, name: str, type: str) -> Order:
        with self.session_factory() as session:
            order = Order(name=name, type=type)
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


class NotFoundError(Exception):

    entity_name: str

    def __init__(self, entity_id):
        super().__init__(f"{self.entity_name} not found, id: {entity_id}")


class UserNotFoundError(NotFoundError):

    entity_name: str = "User"


class OrderNotFoundError(NotFoundError):

    entity_name: str = "Order"
