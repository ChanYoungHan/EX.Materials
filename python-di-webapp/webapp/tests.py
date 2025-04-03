"""Tests module with authentication and authorization."""

from datetime import timedelta
from unittest import mock
import pytest
from fastapi.testclient import TestClient
import io

from webapp.application import app
from webapp.models import User, Image, Order
from webapp.repositories import UserRepository, UserNotFoundError
from webapp.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, get_password_hash
from webapp.utils import PathHelper

# 기본 클라이언트 픽스처
@pytest.fixture
def client():
    yield TestClient(app)

# 관리자 유저 픽스처 (테스트 내 관리자 존재 여부를 위해 사용)
@pytest.fixture
def admin_user():
    return User(
        id=1,
        email="admin@example.com",
        hashed_password=get_password_hash("pwd"),
        is_active=True,
        role="admin"
    )

# 인증/인가를 위한 Fixture로 admin_user와 토큰 생성 및 user_repository override 통합
@pytest.fixture
def admin_auth_header(admin_user):
    token = create_access_token(
        data={"sub": admin_user.email, "role": admin_user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    header = {"Authorization": f"Bearer {token}"}
    # auth_service에서 get_by_email 호출 시 항상 admin_user가 반환되도록 override
    user_repo_mock = mock.Mock(spec=UserRepository)
    user_repo_mock.get_by_email.return_value = admin_user
    app.container.user_repository.override(user_repo_mock)
    yield header
    app.container.user_repository.reset_override()

# /status 엔드포인트 (인증 없이 접근 가능)
def test_status(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "OK"}

# 회원가입 테스트 (auth/signup)
def test_signup(client):
    repository_mock = mock.Mock(spec=UserRepository)
    # 기존에 해당 이메일로 가입된 사용자가 없도록 None을 리턴
    repository_mock.get_by_email.return_value = None
    repository_mock.add.return_value = User(
        id=2,
        email="user@example.com",
        hashed_password=get_password_hash("pwd"),
        is_active=True,
        role="user"
    )
    with app.container.user_repository.override(repository_mock):
        response = client.post(
            "/auth/signup",
            json={"email": "user@example.com", "password": "pwd", "is_active": True}
        )
    assert response.status_code == 200
    expected = {"id": 2, "email": "user@example.com", "is_active": True, "profileImage": None}
    assert response.json() == expected

# 로그인 테스트 (auth/login)
def test_login(client, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    # 로그인 시 관리자 조회가 필요하므로 관리자를 반환하도록 설정
    repository_mock.get_by_email.return_value = admin_user
    with app.container.user_repository.override(repository_mock):
        response = client.post(
            "/auth/login",
            data={"username": "admin@example.com", "password": "pwd"}
        )
    assert response.status_code == 200
    data = response.json()
    # access_token, token_type, 그리고 유저 정보가 포함되어야 함
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    expected_user = {"id": admin_user.id, "email": admin_user.email, "is_active": admin_user.is_active, "profileImage": None}
    assert data["user"] == expected_user

# /users (GET) 리스트 가져오기 - 관리자 권한 필요
def test_get_list(client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    # 인증 과정에서 관리자 조회를 위해 항상 admin_user를 반환
    repository_mock.get_by_email.return_value = admin_user
    repository_mock.get_all.return_value = [
        User(
            id=10,
            email="test1@email.com",
            hashed_password=get_password_hash("pwd"),
            is_active=True,
            role="user"
        ),
        User(
            id=11,
            email="test2@email.com",
            hashed_password=get_password_hash("pwd"),
            is_active=False,
            role="user"
        ),
    ]
    with app.container.user_repository.override(repository_mock):
        response = client.get("/users", headers=admin_auth_header)
    assert response.status_code == 200
    expected = [
        {
            "id": 10,
            "email": repository_mock.get_all.return_value[0].email,
            "is_active": True,
            "profileImage": None,
        },
        {
            "id": 11,
            "email": repository_mock.get_all.return_value[1].email,
            "is_active": False,
            "profileImage": None,
        },
    ]
    assert response.json() == expected

# /users/{id} (GET) 특정 유저 조회 - 관리자 권한 필요
def test_get_by_id(client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    # 인증 과정: 관리자가 존재해야 하므로 admin_user를 반환
    repository_mock.get_by_email.return_value = admin_user
    # 실제 조회하는 사용자는 id=1 (관리자)
    repository_mock.get_by_id.return_value = admin_user
    with app.container.user_repository.override(repository_mock):
        response = client.get("/users/1", headers=admin_auth_header)
    assert response.status_code == 200
    expected = {"id": admin_user.id, "email": admin_user.email, "is_active": admin_user.is_active, "profileImage": None}
    assert response.json() == expected
    repository_mock.get_by_id.assert_called_once_with(1)

# /users/{id} GET 404 오류 테스트
def test_get_by_id_404(client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    # 관리자 인증을 위해 admin_user를 반환하도록 설정
    repository_mock.get_by_email.return_value = admin_user
    repository_mock.get_by_id.side_effect = UserNotFoundError(1)
    with app.container.user_repository.override(repository_mock):
        response = client.get("/users/1", headers=admin_auth_header)
    assert response.status_code == 404

# /users (POST) 신규 유저 추가 테스트 - 관리자 권한 필요
@mock.patch("webapp.services.uuid4", return_value="xyz")
def test_add(mock_uuid, client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    # 관리자 인증 시 get_by_email가 존재해야 하므로 admin_user를 반환
    repository_mock.get_by_email.return_value = admin_user
    repository_mock.add.return_value = User(
        id=3,
        email="xyz@email.com",
        hashed_password=get_password_hash("pwd"),
        is_active=True,
        role="user"
    )
    with app.container.user_repository.override(repository_mock):
        response = client.post("/users", headers=admin_auth_header)
    assert response.status_code == 201
    expected = {
        "id": 3,
        "email": repository_mock.add.return_value.email,
        "is_active": True,
        "profileImage": None,
    }
    assert response.json() == expected
    # 실제 호출 시 추가 인자로 is_active와 role가 포함되므로 그에 맞게 검증합니다.
    repository_mock.add.assert_called_once_with(
        email=expected["email"], 
        password="pwd", 
        is_active=True, 
        role="user"
    )

# /users/{id} (DELETE) 유저 삭제 테스트 - 관리자 권한 필요
def test_remove(client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    repository_mock.get_by_email.return_value = admin_user
    with app.container.user_repository.override(repository_mock):
        response = client.delete("/users/1", headers=admin_auth_header)
    assert response.status_code == 204
    repository_mock.delete_by_id.assert_called_once_with(1)

# /users/{id} (DELETE) 삭제 시 404 오류 테스트
def test_remove_404(client, admin_auth_header, admin_user):
    repository_mock = mock.Mock(spec=UserRepository)
    repository_mock.get_by_email.return_value = admin_user
    repository_mock.delete_by_id.side_effect = UserNotFoundError(1)
    with app.container.user_repository.override(repository_mock):
        response = client.delete("/users/1", headers=admin_auth_header)
    assert response.status_code == 404

def test_get_user_with_profile_image(client, admin_auth_header, admin_user):
    """
    테스트 시나리오: GET /users/{id} 호출 시 사용자의 프로필 이미지가 단일 객체로
    {id, url} 형식으로 반환되는지 확인.
    """
    # 사용자에 프로필 이미지 설정: profile_image 필드에 이미지 ID 101 할당
    admin_user.profile_image = 101
    sample_filename = "sample.png"
    # 기존에 구현된 PathHelper 함수를 사용하여 예상 파일 경로 계산
    expected_file_path = PathHelper.generate_user_profile_path(admin_user.id, 101, sample_filename)
    expected_url = "https://minio.example.com/" + expected_file_path

    repository_mock = mock.Mock(spec=UserRepository)
    repository_mock.get_by_id.return_value = admin_user
    repository_mock.get_by_email.return_value = admin_user

    # 실제 Image 모델을 사용하여 가짜 이미지 객체 생성 (bucket 정보 포함)
    fake_image = Image(id=101, bucket="minio-bucket", path=expected_file_path)

    image_repo_mock = mock.Mock()
    image_repo_mock.get_image_by_id.return_value = fake_image

    minio_repo_mock = mock.Mock()
    minio_repo_mock.get_presigned_url.return_value = expected_url

    with app.container.user_repository.override(repository_mock), \
         app.container.image_repository.override(image_repo_mock), \
         app.container.minio_repository.override(minio_repo_mock):
        response = client.get(f"/users/{admin_user.id}", headers=admin_auth_header)
        assert response.status_code == 200
        data = response.json()
        # profileImage 필드가 올바르게 {id, url} 형태로 반환되는지 검증
        assert "profileImage" in data
        assert data["profileImage"] == {"id": 101, "url": expected_url}

@mock.patch("webapp.services.uuid.uuid4")
def test_upload_order_image_returns_order_with_image_list(mock_uuid4, client, admin_auth_header, admin_user):
    """
    테스트 시나리오: POST /orders/{order_id}/order-image 호출 시 업로드된 이미지가 Order에 추가되어
    반환되는 OrderResponse 내의 orderImages 필드가 복수 개체(리스트)로 반환되고,
    각 이미지 객체가 {id, url} 형태로 되어 있는지 확인.
    """
    # 고정된 uuid 생성 (패치된 uuid.uuid4()가 반환)
    fake_uuid = type("FakeUUID", (), {"hex": "fixeduuid"})()
    mock_uuid4.return_value = fake_uuid

    order_id = 100
    sample_filename = "sample.png"
    # 기존 PathHelper 함수를 사용하여 예상 파일 경로 계산
    expected_file_path = PathHelper.generate_order_image_path(order_id, "fixeduuid", sample_filename)
    expected_url = "https://minio.example.com/" + expected_file_path

    # 실제 Order 객체를 생성하여 order_image_list에 이미지 ID 300 추가
    order_obj = Order(
        id=order_id,
        name="Test Order",
        type="dummy",
        quantity="1"
    )
    order_obj.order_image_list = [300]
    # 테스트 시 response에서 변환된 값을 나타내기 위해 orderImages 속성을 추가(실제 구현에서는 서비스에서 수행)
    order_obj.orderImages = [{"id": 300, "url": expected_url}]

    order_repo_mock = mock.Mock()
    order_repo_mock.add_order_image.return_value = order_obj

    # 실제 Image 모델을 사용하여 가짜 이미지 객체 생성 (bucket 정보 포함)
    fake_image = Image(id=300, bucket="minio-bucket", path=expected_file_path)

    image_repo_mock = mock.Mock()
    image_repo_mock.add_image.return_value = fake_image
    image_repo_mock.get_image_by_id.return_value = fake_image

    minio_repo_mock = mock.Mock()
    # upload_file 메서드 호출 시 임의의 오브젝트 키 반환 (사용되지 않음)
    minio_repo_mock.upload_file.return_value = "object_key_123"
    minio_repo_mock.get_presigned_url.return_value = expected_url

    user_repo_mock = mock.Mock()
    # 인증용: admin_user 반환
    user_repo_mock.get_by_email.return_value = admin_user

    with app.container.order_repository.override(order_repo_mock), \
         app.container.image_repository.override(image_repo_mock), \
         app.container.minio_repository.override(minio_repo_mock), \
         app.container.user_repository.override(user_repo_mock):
        file_content = b"dummy image data"
        files = {
            "file": ("sample.png", io.BytesIO(file_content), "image/png")
        }
        response = client.post(f"/orders/{order_id}/order-image", headers=admin_auth_header, files=files)
        assert response.status_code == 200
        data = response.json()
        # orderImages 필드가 존재하며, 리스트 내의 각 이미지가 {id, url} 형태인지 확인
        assert "orderImageList" in data
        expected_order_images = [{"id": 300, "url": expected_url}]
        assert data["orderImageList"] == expected_order_images

########################################################
# ORDER 플로우 테스트
########################################################

# ① 오더 생성 테스트
def test_create_order(client, admin_auth_header):
    # 가짜 오더 객체 생성 (quantity는 모델에서는 문자열이지만, 스키마에서는 int로 변환)
    fake_order = Order(
        id=100,
        name="Test Order",
        type="dummy",
        quantity="1"
    )
    fake_order.order_image_list = []

    order_repo_mock = mock.Mock()
    order_repo_mock.add.return_value = fake_order
    order_repo_mock.get_by_id.return_value = fake_order

    with app.container.order_repository.override(order_repo_mock):
        response = client.post(
            "/orders",
            json={"name": "Test Order", "type": "dummy", "quantity": 1},
            headers=admin_auth_header
        )
    assert response.status_code == 201
    expected = {
        "id": 100,
        "name": "Test Order",
        "type": "dummy",
        "quantity": 1,
        "orderImageList": []
    }
    assert response.json() == expected

# ② 선택한 오더 이미지 삭제 테스트
def test_delete_selected_order_image(client, admin_auth_header):
    order_id = 100
    # 초기 오더: 두 개의 이미지 [300, 301]가 있다고 가정
    initial_order = Order(
        id=order_id,
        name="Test Order",
        type="dummy",
        quantity="1"
    )
    initial_order.order_image_list = [300, 301]

    # 삭제 후 업데이트된 오더: 이미지 300이 제거되어 [301]만 남음
    updated_order = Order(
        id=order_id,
        name="Test Order",
        type="dummy",
        quantity="1"
    )
    updated_order.order_image_list = [301]

    # image_id 300 (삭제 대상)와 301 (남은 이미지)에 대해 실제 Image 객체를 상속한 Mock 객체 생성
    mock_image_deletion = mock.Mock(spec=Image)
    mock_image_deletion.id = 300
    mock_image_deletion.order_id = order_id
    mock_image_deletion.path = f"orders/{order_id}/300_sample.png"

    mock_image_remaining = mock.Mock(spec=Image)
    mock_image_remaining.id = 301
    mock_image_remaining.order_id = order_id
    mock_image_remaining.path = f"orders/{order_id}/301_sample.png"

    # 남은 이미지의 presigned URL 예상 값
    expected_url = f"https://minio.example.com/orders/{order_id}/301_sample.png"

    order_repo_mock = mock.Mock()
    order_repo_mock.get_by_id.return_value = initial_order
    order_repo_mock.delete_order_image_by_id.return_value = updated_order

    image_repo_mock = mock.Mock()
    # image_id에 따라 올바른 Mock Image 객체를 반환하는 side_effect 설정
    def get_image_by_id_side_effect(image_id):
        if image_id == 300:
            return mock_image_deletion
        elif image_id == 301:
            return mock_image_remaining
        return None
    image_repo_mock.get_image_by_id.side_effect = get_image_by_id_side_effect

    minio_repo_mock = mock.Mock()
    # 파일 경로에 따라 URL을 생성하도록 설정합니다.
    minio_repo_mock.get_presigned_url.side_effect = lambda path: f"https://minio.example.com/{path}"

    with app.container.order_repository.override(order_repo_mock), \
         app.container.image_repository.override(image_repo_mock), \
         app.container.minio_repository.override(minio_repo_mock):
        response = client.delete(f"/orders/{order_id}/order-image/300", headers=admin_auth_header)

    assert response.status_code == 200
    data = response.json()
    expected_order_images = [{"id": 301, "url": expected_url}]
    expected_response = {
        "id": order_id,
        "name": "Test Order",
        "type": "dummy",
        "quantity": 1,
        "orderImageList": expected_order_images
    }
    assert data == expected_response
