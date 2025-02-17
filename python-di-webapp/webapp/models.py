"""Models module."""

from sqlalchemy import Column, String, Boolean, Integer, DateTime
from datetime import datetime, timezone
from .database import Base


class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    email = Column(String, unique=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    # quantity = Column(String, nullable=False)
