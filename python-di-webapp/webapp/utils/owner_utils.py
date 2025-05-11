# 소유자 인증 관련 유틸리티 함수
from typing import Optional, TypeVar, Callable
from fastapi import Request, HTTPException
import functools

T = TypeVar('T')

class OwnerUtils:
    """소유자 인증 관련 유틸리티 함수"""
    
    @staticmethod
    def get_owner_email(request: Request) -> Optional[str]:
        """요청 상태에서 소유자 이메일을 추출합니다."""
        return getattr(request.state, "owner_email", None)
    
    @staticmethod
    def require_owner_email(request: Request) -> str:
        """소유자 이메일이 없으면 예외를 발생시킵니다."""
        owner_email = OwnerUtils.get_owner_email(request)
        if not owner_email:
            raise HTTPException(status_code=401, detail="Owner authentication required")
        return owner_email
    
    @staticmethod
    def with_owner(func: Callable) -> Callable:
        """소유자 이메일을 서비스 함수에 주입하는 데코레이터"""
        @functools.wraps(func)
        def wrapper(service, *args, request: Request = None, **kwargs):
            if request:
                owner_email = OwnerUtils.get_owner_email(request)
                kwargs['owner_email'] = owner_email
            return func(service, *args, **kwargs)
        return wrapper
    
    @staticmethod
    def filter_by_owner(items: list, owner_field: str, owner_email: Optional[str]) -> list:
        """소유자 이메일로 항목을 필터링합니다."""
        if not owner_email:
            return items
        
        return [item for item in items if getattr(item, owner_field, None) == owner_email]