"""Models module."""

from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    bucket = Column(String, nullable=False)
    path = Column(String, nullable=False)

    # 이미지가 특정 Order나 User에 속할 수 있도록 외래키를 추가합니다.
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)

class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    email = Column(String, unique=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    role = Column(String, default="user")
    profile_image = Column(Integer, ForeignKey("images.id"), nullable=True)

    # profile_image 컬럼을 통해 한 개의 Image 객체와 연결합니다.
    profile_image_obj = relationship("Image", foreign_keys=[profile_image], uselist=False)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    quantity = Column(String, nullable=False)
    # 기존의 order_image_list 컬럼은 제거합니다.
    # 대신, Image의 외래키(order_id)를 통해 역참조 관계(images)를 활용합니다.
    images = relationship("Image", backref="order", foreign_keys=[Image.order_id])
