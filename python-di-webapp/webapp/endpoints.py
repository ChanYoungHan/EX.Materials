"""Endpoints module."""

from fastapi import APIRouter, Depends, Response, status, HTTPException
from dependency_injector.wiring import inject, Provide
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from .containers import Container
from .services import UserService, OrderService
from .schemas import UserResponse, OrderResponse, OrderRequest, UserRequest
from .security import verify_password, get_password_hash, create_access_token

user_router = APIRouter(prefix="/users", tags=["users"])
order_router = APIRouter(prefix="/orders", tags=["orders"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
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

########################################################
# AUTH
########################################################
@auth_router.post("/signup", response_model=UserResponse)
def signup(user_req: UserRequest, user_service: UserService = Depends(get_user_service)):
    # 이미 존재하는 email 체크(중복 가입 방지)
    # 예시용으로 단순 처리
    existing_user = user_service.get_user_by_email(user_req.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="해당 이메일로 가입된 사용자가 이미 존재합니다."
        )
    # 비밀번호 해싱 후 생성
    hashed_pw = get_password_hash(user_req.password)
    new_user = user_service.create_user_with_credential(
        email=user_req.email,
        hashed_password=hashed_pw,
        is_active=user_req.is_active,
        role="user",  # 새로 가입하면 일반 사용자
    )
    return new_user

@auth_router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), user_service: UserService = Depends(get_user_service)):
    # email이 username 필드에 들어온다고 가정
    user = user_service.get_user_by_email(form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}

# 토큰으로부터 유저 정보 추출
def get_current_user(token: str = Depends(oauth2_scheme), user_service: UserService = Depends(get_user_service)):
    from .security import decode_access_token
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    email = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=401, detail="토큰 정보에 이메일이 없습니다.")
    user = user_service.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="해당 유저가 존재하지 않습니다.")
    return user

def require_admin(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 없습니다."
        )
    return current_user
########################################################
# USER
########################################################
@user_router.get("", response_model=list[UserResponse])
def get_list(
        current_user=Depends(get_current_user),
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


@user_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
        user_id: int,
        user_service: UserService = Depends(get_user_service),
) -> Response:
    return user_service.delete_user_by_id(user_id)


########################################################
# ORDER
########################################################

@order_router.get("", response_model=list[OrderResponse])
def get_orders(
        current_user=Depends(require_admin),
        order_service: OrderService = Depends(get_order_service)
) -> list[OrderResponse]:
    return order_service.get_orders()

@order_router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, order_service: OrderService = Depends(get_order_service)) -> OrderResponse | Response:
    return order_service.get_order_by_id(order_id)

@order_router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def add_order(order_request: OrderRequest, order_service: OrderService = Depends(get_order_service)) -> OrderResponse:
    return order_service.create_order(order_request)

@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_order(order_id: int, order_service: OrderService = Depends(get_order_service)) -> Response:
    return order_service.delete_order_by_id(order_id)

