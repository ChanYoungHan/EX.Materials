"""Endpoints module."""

import asyncio
import time
from fastapi import APIRouter, Depends, Response, status, UploadFile, File, Query, Path, Request, Header
from dependency_injector.wiring import inject, Provide
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional, List

from .containers import Container
from .services import UserService, OrderService, AuthService, MainPageService, TestNoSQLService
from .schemas import UserResponse, OrderResponse, OrderRequest, UserRequest, AuthResponse, ImageResponse, TestDocumentCreate, TestDocumentUpdate, TestDocumentResponse
from .utils.owner_utils import OwnerUtils

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

@inject
def get_landing_service(
    main_page_service: MainPageService = Depends(Provide[Container.main_page_service])
) -> MainPageService:
    return main_page_service

@inject
def get_nosql_service(
    nosql_service: TestNoSQLService = Depends(Provide[Container.nosql_service])
) -> TestNoSQLService:
    return nosql_service

def current_user_dependency(token: str = Depends(oauth2_scheme), auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.get_current_user(token)

def admin_dependency(current_user = Depends(current_user_dependency), auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.require_admin(current_user)

async def get_owner_email(request: Request) -> Optional[str]:
    """요청 상태에서 소유자 이메일을 추출합니다."""
    return OwnerUtils.get_owner_email(request)

async def require_owner_email(request: Request) -> str:
    """소유자 이메일이 없으면 예외를 발생시킵니다."""
    return OwnerUtils.require_owner_email(request)

test_router = APIRouter(prefix="/test", tags=["test"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(admin_dependency)])
order_router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(admin_dependency)])
main_page_admin_router = APIRouter(
    prefix="/mainPageAdmin", 
    tags=["mainPageAdmin"],
    dependencies=[Depends(admin_dependency)]  # 관리자 권한 검사
)
main_page_router = APIRouter(
    prefix="/mainPage", 
    tags=["mainPage"]
)
nosql_router = APIRouter(
    prefix="/nosql",
    tags=["nosql"],
    dependencies=[Depends(admin_dependency)]  # admin 권한 필요
)

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

# 소유자 인증 엔드포인트
@test_router.get("/api/protected/test-owner")
async def test_owner(request: Request):
    owner_email = getattr(request.state, "owner_email", None)
    return {
        "message": "Protected endpoint",
        "owner_email": owner_email
    }

@test_router.get("/api/protected/test-ownerHeaderDefined", 
                 summary="소유자 헤더 테스트",
                 description="Owner 헤더를 통해 소유자 이메일을 확인하는 테스트 엔드포인트")
async def test_owner_email(owner: str = Header(None, alias="Owner", description="소유자 이메일")):
    return {
        "message": "Protected endpoint",
        "Owner": owner
    }

########################################################
# ORDER
########################################################

@order_router.get("", response_model=list[OrderResponse])
def get_orders(
        order_service: OrderService = Depends(get_order_service),
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


########################################################
# MainPage ADMIN
########################################################
@main_page_admin_router.put("/uploadImage/main", response_model=ImageResponse)
def upload_main_image(
    file: UploadFile = File(...),
    main_page_service: MainPageService = Depends(get_landing_service)
):
    """랜딩 페이지 메인 이미지를 업로드하고 설정합니다."""
    return main_page_service.set_main_image(file)

@main_page_admin_router.delete("/deleteImage/main", status_code=status.HTTP_204_NO_CONTENT)
def delete_main_image(
    main_page_service: MainPageService = Depends(get_landing_service)
):
    """랜딩 페이지 메인 이미지를 삭제합니다."""
    main_page_service.delete_main_image()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@main_page_admin_router.post("/uploadImage/gallery", response_model=List[ImageResponse])
def upload_gallery_image(
    file: UploadFile = File(...),
    main_page_service: MainPageService = Depends(get_landing_service)
):
    """랜딩 페이지 갤러리에 이미지를 추가합니다."""
    return main_page_service.add_gallery_image(file)

@main_page_admin_router.delete("/deleteImage/gallery", status_code=status.HTTP_204_NO_CONTENT)
def delete_gallery_image(
    image_id: int = Query(..., description="삭제할 이미지 ID"),
    main_page_service: MainPageService = Depends(get_landing_service)
):
    """랜딩 페이지 갤러리에서 이미지를 삭제합니다."""
    main_page_service.delete_gallery_image(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

########################################################
# MainPage
########################################################
@main_page_router.get("/mainImage", response_model=Optional[ImageResponse])
def get_main_image(
    main_page_service: MainPageService = Depends(get_landing_service),
    owner_email: Optional[str] = Depends(get_owner_email)   
):
    """현재 설정된 랜딩 페이지 메인 이미지를 조회합니다."""
    return main_page_service.get_main_image(owner_email)

@main_page_router.get("/galleryImages", response_model=List[ImageResponse])
def get_gallery_images(
    main_page_service: MainPageService = Depends(get_landing_service),
    owner_email: Optional[str] = Depends(get_owner_email)       
):
    """현재 설정된 랜딩 페이지 갤러리 이미지 목록을 조회합니다."""
    return main_page_service.get_gallery_images(owner_email)

########################################################
# NoSQL
########################################################

@nosql_router.post("", response_model=TestDocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    document: TestDocumentCreate,
    nosql_service: TestNoSQLService = Depends(get_nosql_service)
):
    """새로운 테스트 문서를 생성합니다."""
    return nosql_service.create_document(document.model_dump())

@nosql_router.get("", response_model=List[TestDocumentResponse])
def get_documents(
    limit: int = Query(100, ge=1, le=1000, description="한 번에 가져올 최대 문서 수"),
    skip: int = Query(0, ge=0, description="건너뛸 문서 수"),
    nosql_service: TestNoSQLService = Depends(get_nosql_service)
):
    """테스트 문서 목록을 조회합니다."""
    return nosql_service.get_documents(limit=limit, skip=skip)

@nosql_router.get("/{document_id}", response_model=TestDocumentResponse)
def get_document(
    document_id: str = Path(..., description="조회할 문서의 ID"),
    nosql_service: TestNoSQLService = Depends(get_nosql_service)
):
    """ID로 테스트 문서를 조회합니다."""
    return nosql_service.get_document_by_id(document_id)

@nosql_router.put("/{document_id}", response_model=TestDocumentResponse)
def update_document(
    document: TestDocumentUpdate,
    document_id: str = Path(..., description="업데이트할 문서의 ID"),
    nosql_service: TestNoSQLService = Depends(get_nosql_service)
):
    """ID로 테스트 문서를 업데이트합니다."""
    # None이 아닌 필드만 업데이트
    update_data = {k: v for k, v in document.model_dump().items() if v is not None}
    return nosql_service.update_document(document_id, update_data)

@nosql_router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str = Path(..., description="삭제할 문서의 ID"),
    nosql_service: TestNoSQLService = Depends(get_nosql_service)
):
    """ID로 테스트 문서를 삭제합니다."""
    nosql_service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
