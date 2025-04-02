"""Tests module with authentication and authorization."""

from datetime import timedelta
from unittest import mock
import pytest
from fastapi.testclient import TestClient

from webapp.application import app
from webapp.models import User
from webapp.repositories import UserRepository, UserNotFoundError
from webapp.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, get_password_hash

# 기본 클라이언트 픽스처
@pytest.fixture
def client():
    yield TestClient(app)

# 관리자 인증 헤더를 생성하는 픽스처 (관리자 권한 필요)
@pytest.fixture
def admin_auth_header():
    token = create_access_token(
        data={"sub": "admin@example.com", "role": "admin"},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"Authorization": f"Bearer {token}"}

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
