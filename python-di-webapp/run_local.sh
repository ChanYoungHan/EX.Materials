#!/bin/bash

# 환경 변수 파일 로드
export $(cat .env.local | xargs)

# 데이터베이스 마이그레이션 실행
alembic upgrade head

# 애플리케이션 실행
uvicorn webapp.application:app --host 0.0.0.0 --port 8000 --reload