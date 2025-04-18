"""Endpoints module."""

import asyncio
import time
from fastapi import APIRouter, Depends, Response, status, UploadFile, File
from dependency_injector.wiring import inject, Provide
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from .containers import Container
from .services import UserService, OrderService, AuthService
from .schemas import UserResponse, OrderResponse, OrderRequest, UserRequest, AuthResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

@inject
def get_user_service(
    user_service: UserService = Depends(Provide[Container.user_service])
) -> UserService:
    return user_service

@inject
def get_order_service(
    order_service: OrderService = Depends(Provide[Container.order_service])
) -> OrderService:
    return order_service

@inject
def get_auth_service(auth_service: AuthService = Depends(Provide[Container.auth_service])) -> AuthService:
    return auth_service

def current_user_dependency(token: str = Depends(oauth2_scheme), auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.get_current_user(token)

def admin_dependency(current_user = Depends(current_user_dependency), auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.require_admin(current_user)

test_router = APIRouter(prefix="/test", tags=["test"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(admin_dependency)])
order_router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(admin_dependency)])


########################################################
# AUTH
########################################################
@auth_router.post("/signup", response_model=UserResponse)
def signup(user_req: UserRequest, auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.signup(user_req)

@auth_router.post("/login", response_model=AuthResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.login(form_data.username, form_data.password)

########################################################
# USER
########################################################
@user_router.get("", response_model=list[UserResponse])
def get_list(
        user_service: UserService = Depends(get_user_service),
) -> list[UserResponse]:
    return user_service.get_users()


@user_router.get("/{user_id}", response_model=UserResponse)
def get_by_id(
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> UserResponse | Response:
    return user_service.get_user_by_id(user_id)


@user_router.post("", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def add(
        user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    return user_service.create_user()

# === User 1번 요구사항: 로직 변경 (기존 엔드포인트 유지) ===
@user_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user( # 함수명 명확화 (remove -> remove_user)
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> Response:
    """사용자 및 연관된 프로필 이미지를 삭제합니다."""
    return user_service.delete_user_by_id(user_id) # 서비스 메서드 호출 (수정된 로직)

# === User 2번 요구사항: 신규 엔드포인트 추가 ===
@user_router.delete("/{user_id}/profile-image", response_model=UserResponse)
def remove_profile_image(
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> UserResponse | Response:
    """사용자의 프로필 이미지만 삭제합니다 (S3 및 DB)."""
    return user_service.delete_profile_image(user_id) # 새 서비스 메서드 호출

# 이미지 업로드 엔드포인트 (User 프로필 이미지)
@user_router.post("/{user_id}/profile-image", response_model=UserResponse)
def upload_profile_image(
        user_id: int,
        file: UploadFile = File(...),
        user_service: UserService = Depends(get_user_service),
):
    return user_service.upload_profile_image(user_id, file)

########################################################
# TEST
########################################################
'''
Remove if this templates work on production
'''
# IO 집약적 엔드포인트(이벤트 루프 사용)
@test_router.get("/async-wait")
async def async_wait():
    await asyncio.sleep(5)
    return {"message": "Hello, World!"}

# IO 집약적 엔드포인트(쓰레드 풀 사용)
@test_router.get("/sync-wait")
def sync_wait():
    time.sleep(5)
    return {"message": "Hello, World!"}

# CPU 집약적 엔드포인트(쓰레드 풀 사용)
@test_router.get("/cpu-bound")
def cpu_bound():
    return sum(i*i for i in range(10**7))

########################################################
# ORDER
########################################################

@order_router.get("", response_model=list[OrderResponse])
def get_orders(
        order_service: OrderService = Depends(get_order_service)
) -> list[OrderResponse]:
    return order_service.get_orders()

@order_router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, order_service: OrderService = Depends(get_order_service)) -> OrderResponse | Response:
    return order_service.get_order_by_id(order_id)

@order_router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def add_order(order_request: OrderRequest, order_service: OrderService = Depends(get_order_service)) -> OrderResponse:
    return order_service.create_order(order_request)

# === Orders 1번 요구사항: 기존 엔드포인트 수정 (서비스 메서드 호출 변경 및 로직 수정) ===
@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_order( # 함수명 유지 또는 delete_order_by_id로 변경 고려
        order_id: int,
        order_service: OrderService = Depends(get_order_service)
) -> Response:
    """주문 및 연관된 모든 이미지를 삭제합니다."""
    # 기존: return order_service.delete_order_image(order_id) -> 이름/로직 변경된 메서드 호출
    return order_service.delete_order_by_id(order_id)

# === Orders 2번 요구사항: 기존 엔드포인트 유지 (로직 검증) ===
@order_router.delete("/{order_id}/order-image/{image_id}", response_model=OrderResponse)
def delete_single_order_image( # 함수명 유지
    order_id: int,
    image_id: int,
    order_service: OrderService = Depends(get_order_service)
) -> OrderResponse | Response:
    """주문에 속한 특정 이미지를 삭제합니다."""
    return order_service.delete_single_order_image(order_id, image_id) # 기존 서비스 메서드 호출

# === Orders 3번 요구사항: 기존 엔드포인트 유지 (로직 검증) ===
@order_router.delete("/{order_id}/order-image", response_model=OrderResponse)
def delete_all_order_images( # 함수명 유지
    order_id: int,
    order_service: OrderService = Depends(get_order_service)
) -> OrderResponse | Response:
    """주문에 속한 모든 이미지를 삭제합니다."""
    return order_service.delete_all_order_images(order_id) # 기존 서비스 메서드 호출

# 이미지 업로드 엔드포인트 (Order 이미지)
@order_router.post("/{order_id}/order-image", response_model=OrderResponse)
def upload_order_image(
        order_id: int,
        file: UploadFile = File(...),
        order_service: OrderService = Depends(get_order_service),
):
    return order_service.upload_order_image(order_id, file)

