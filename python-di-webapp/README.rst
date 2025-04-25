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
- 2025-04-25 : 로컬 개발 환경을 Docker 마운트에서 pyenv로 변경

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
   export $(cat .env.local | xargs)
   alembic upgrade head
   uvicorn webapp.application:app --host 0.0.0.0 --port 8000 --reload

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

   # 환경 변수 설정
   export $(cat .env.local | xargs)
   
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