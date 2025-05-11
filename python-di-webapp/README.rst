FastAPI + SQLAlchemy + Dependency Injector Example
==================================================

ResearchNote
---------

- 2025-02-18 : Alembic 마이그레이션 추가
   참고 : `LinkToBlog <https://imaginemaker.notion.site/Alembic-19c865424aed8099bcc9d29bf3f0d760?pvs=4>`_
- 2025-03-15 : Async 리서치
   참고 : `LinkToBlog <https://imaginemaker.notion.site/Async-DI-python-19a865424aed807a9dc7c9a12f28f990?pvs=4>`_
- 2025-03-29 : GraphQL 도입
   참고 : `LinkToBlog <https://imaginemaker.notion.site/GraphQL-1c2865424aed80419f78d3f6d7ad0694?pvs=4>`_
- 2025-04-02 : 이미지 `backref` 연관 관계 추가
   참고 : `LinkToBlog <https://imaginemaker.notion.site/DI-template-ImageRouter-192865424aed809f974cf53516d31641?pvs=4>`_
- 2025-04-26 : NoSQL 도입
   참고 : `LinkToBlog <https://imaginemaker.notion.site/DI-template-noSQL-1e0865424aed8059b878f1f47fc8f09e?pvs=4>`_
- 2025-05-11 : 소유자 인증 시스템 추가
   참고 : `LinkToBlog <https://imaginemaker.notion.site/RSA-Owner-Authentication-12d865424aed80a9eb7d6c8d91e8a42b?pvs=4>`_

This is a `FastAPI <https://fastapi.tiangolo.com/>`_ +
`SQLAlchemy <https://www.sqlalchemy.org/>`_ +
`Dependency Injector <https://python-dependency-injector.ets-labs.org/>`_ example application.

Thanks to `@ShvetsovYura <https://github.com/ShvetsovYura>`_ for providing initial example:
`FastAPI_DI_SqlAlchemy <https://github.com/ShvetsovYura/FastAPI_DI_SqlAlchemy>`_.

로컬 개발 환경 설정 (pyenv)
------------------------

pyenv를 사용한 로컬 개발 환경 설정 방법입니다.

1. pyenv 및 Python 설치:

.. code-block:: bash

   # pyenv 설치 (MacOS 예시)
   brew install pyenv
   
   # Python 설치
   pyenv install 3.11
   
   # 프로젝트 디렉토리에서 Python 버전 설정
   pyenv local 3.11

2. 가상 환경 생성 및 패키지 설치:

.. code-block:: bash

   # 가상 환경 생성
   pyenv virtualenv 3.11 di-server
   
   # 가상 환경 활성화
   pyenv activate di-server
   
   # 패키지 설치
   pip install -r requirements.txt

3. 데이터베이스 실행:

로컬 PostgreSQL을 사용하거나 도커로 PostgreSQL만 실행할 수 있습니다.

.. code-block:: bash

   # Docker를 사용하여 PostgreSQL만 실행
   docker-compose -f docker-compose-db.yml up -d

4. 환경 변수 설정:

.env.local 파일을 수정하여 로컬 개발 환경에 맞게 설정합니다.

5. 데이터베이스 마이그레이션 및 애플리케이션 실행:

.. code-block:: bash

   # 실행 스크립트를 사용하여 마이그레이션 및 애플리케이션 실행
   chmod +x run_local.sh
   ./run_local.sh
   
   # 또는 개별적으로 실행
   alembic -c alembic.local.ini upgrade head
   uvicorn webapp.application:app --host 0.0.0.0 --port 8000 --reload

소유자 인증 시스템 설정
------------------

소유자 인증 시스템은 RSA 비대칭 키 암호화를 사용하여 이메일 주소를 안전하게 전송하는 기능을 제공합니다.

1. 키 생성:

.. code-block:: bash

   # 기본 설정으로 키 생성
   python generate_keys.py
   
   # 또는 커스텀 디렉토리와 키 크기 지정
   python generate_keys.py --directory keys --size 1024

2. 설정 파일 수정 (config.yml):

.. code-block:: yaml

   # 소유자 인증 관련 설정
   owner_auth:
     keys_dir: "keys"                # 키 저장 디렉토리 (상대 경로 또는 절대 경로)
     private_key_filename: "private_key.pem"  # 비밀키 파일명
     public_key_filename: "public_key.pem"    # 공개키 파일명
     owner_header_name: "Owner"      # HTTP 헤더 이름
     log_owner_email: true           # 디버그용: 복호화된 이메일 로깅 (개발 환경에서만 true로 설정)
     protected_paths:                # 소유자 인증이 필요한 경로 목록
       - "/api/protected"
       - "/api/owner/protected-test"
       # 여기에 보호할 경로를 추가하세요

3. API 테스트:

.. code-block:: bash

   # 공개키 가져오기
   curl http://localhost:8000/api/public-key
   
   # 테스트 엔드포인트 호출 (암호화된 이메일 필요)
   curl -X GET http://localhost:8000/api/owner/protected-test \
     -H "owner: 암호화된_이메일_문자열"

4. 테스트 클라이언트:

제공된 HTML 클라이언트를 사용하여 소유자 인증 시스템을 테스트할 수 있습니다:

- HTML 파일을 웹 서버에서 호스팅하세요 (HTTPS 또는 localhost)
- 서버 URL과 엔드포인트를 설정하세요
- 공개키를 가져오거나 직접 입력하세요
- 이메일을 입력하고 암호화/전송하세요

5. 프로덕션 배포:

.. code-block:: yaml

   # docker-compose.yml에서 볼륨 설정
   volumes:
     - ./keys:/app/keys  # 키 디렉토리를 볼륨으로 마운트
   
   # config.yml에서 프로덕션 설정
   owner_auth:
     log_owner_email: false  # 프로덕션에서는 로깅 비활성화

6. 소유자 인증 엔드포인트 사용:

.. code-block:: python

   from fastapi import APIRouter, Request
   
   router = APIRouter()
   
   @router.get("/api/protected-resource")
   async def protected_resource(request: Request):
       # owner_email은 미들웨어에서 설정됨
       owner_email = getattr(request.state, "owner_email", None)
       
       if not owner_email:
           return {"error": "Authentication required"}
       
       # 소유자 이메일로 추가 작업 수행
       return {
           "message": "Authenticated",
           "owner_email": owner_email
       }

7. 문제 해결:

- "Cannot read properties of undefined (reading 'importKey')" 오류:
  클라이언트를 HTTPS 또는 localhost 환경에서 실행하거나, JSEncrypt 라이브러리를 사용하세요.
  
- 복호화 실패:
  키 페어가 올바르게 생성되었는지 확인하고, 클라이언트와 서버 간에 동일한 키를 사용하는지 확인하세요.
  
- 미들웨어 문제:
  보호 경로가 config.yml에 올바르게 설정되었는지 확인하고, 로그를 검토하세요.

운영 환경 배포
-----------

운영 환경은 Docker 컨테이너를 사용합니다.

.. code-block:: bash

   # 운영 환경 배포
   docker-compose build
   docker-compose up -d

API 문서
-------

애플리케이션이 실행된 후 http://127.0.0.1:8000/docs 에서 API 문서를 확인할 수 있습니다.

테스트
----

단위 테스트를 실행하려면:

로컬 환경에서:

.. code-block:: bash

   # 테스트 실행
   pytest webapp/tests.py --cov=webapp

Docker 환경에서:

.. code-block:: bash

   docker-compose run --rm webapp py.test webapp/tests.py --cov=webapp

Migrations
----------

새로운 마이그레이션을 생성하려면:

로컬 환경에서:

.. code-block:: bash

   # 환경 변수 설정
   export $(cat .env.local | xargs)
   
   # 마이그레이션 생성
   alembic revision --autogenerate -m "migration_name"

Docker 환경에서:

.. code-block:: bash

   docker-compose run --rm webapp alembic revision --autogenerate -m "migration_name"