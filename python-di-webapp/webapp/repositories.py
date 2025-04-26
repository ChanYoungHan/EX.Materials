import asyncio

from contextlib import AbstractContextManager
from typing import Callable, Iterator, BinaryIO, List, Optional, Any, Dict
from datetime import timedelta, datetime
from bson import ObjectId
from pymongo.collection import Collection


from sqlalchemy.orm import Session, joinedload
from minio import Minio
from minio.error import S3Error

from .models import User, Order, Image, MainPageSetting
from .schemas import OrderRequest
from .logger_config import configure_logger

logger = configure_logger()

class UserRepository:

    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def get_all(self) -> Iterator[User]:
        with self.session_factory() as session:
            return session.query(User).all()

    def get_by_id(self, user_id: int) -> User:
        with self.session_factory() as session:
            user = session.query(User).filter(User.id == user_id).scalar()
            if not user:
                raise UserNotFoundError(user_id)
            return user

    def get_by_email(self, email: str) -> User:
        with self.session_factory() as session:
            return session.query(User).filter(User.email == email).first()

    def add(self, email: str, password: str, is_active: bool, role: str = "user") -> User:
        with self.session_factory() as session:
            user = User(email=email, hashed_password=password, is_active=is_active, role=role)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def delete_by_id(self, user_id: int) -> None:
        # User 삭제 전 profile_image FK 제약 조건을 고려해야 할 수 있음
        # -> 서비스 계층에서 이미지 삭제 후 User 삭제 호출 권장
        # -> 또는 DB 레벨에서 ON DELETE SET NULL/CASCADE 설정 고려
        with self.session_factory() as session:
            entity: User = session.query(User).filter(User.id == user_id).first()
            if not entity:
                raise UserNotFoundError(user_id)
            session.delete(entity)
            session.commit()

    def update_profile_image(self, user_id: int, image_id: Optional[int]) -> User: # image_id를 Optional[int]로 변경
        """사용자의 프로필 이미지를 업데이트하거나 제거합니다."""
        with self.session_factory() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                raise UserNotFoundError(user_id)
            user.profile_image = image_id # None을 전달하면 FK가 NULL로 설정됨
            session.commit()
            session.refresh(user)
            # profile_image_obj 관계 로드를 위해 재조회 또는 expire 처리 필요 가능성
            # 여기서는 간단히 refresh된 user 반환
            return user

    # === User 2번 요구사항을 위한 추가 메서드 ===
    def clear_profile_image_fk(self, user_id: int) -> User:
        """User 테이블의 profile_image 외래 키를 NULL로 설정합니다."""
        return self.update_profile_image(user_id, None) # 기존 메서드 재활용


class OrderRepository:
    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def _base_order_query(self, session):
        # Order 객체 조회 시 images 관계를 joinedload로 미리 로드합니다.
        return session.query(Order).options(joinedload(Order.images))

    def get_all(self) -> Iterator[Order]:
        with self.session_factory() as session:
            return self._base_order_query(session).all()

    def get_by_id(self, order_id: int) -> Order:
        with self.session_factory() as session:
            order = self._base_order_query(session).filter(Order.id == order_id).first()
            if not order:
                raise OrderNotFoundError(order_id)
            return order

    def add(self, order_request: OrderRequest) -> Order:
        with self.session_factory() as session:
            order = Order(**order_request.model_dump())
            session.add(order)
            session.commit()
            session.refresh(order)
            return order

    def delete_by_id(self, order_id: int) -> None:
        # Order 삭제 전 Image의 order_id FK 제약 조건 고려
        # -> 서비스 계층에서 관련 Image 먼저 삭제 권장
        # -> 또는 DB 레벨에서 ON DELETE CASCADE 설정 고려
        with self.session_factory() as session:
            entity: Order = session.query(Order).filter(Order.id == order_id).first()
            if not entity:
                raise OrderNotFoundError(order_id)
            session.delete(entity)
            session.commit()

    # === Orders 2번 요구사항을 위한 메서드 (이름 명확화 제안) ===
    # 기존: delete_order_image_by_id
    def delete_single_image_for_order(self, order_id: int, image_id: int) -> Order:
        """주문에 속한 특정 이미지를 DB에서 삭제합니다."""
        with self.session_factory() as session:
            # 이미지가 삭제된 후 Order 객체를 반환해야 하므로, 먼저 Order를 조회
            order = self._base_order_query(session).filter(Order.id == order_id).first()
            if not order:
                raise OrderNotFoundError(order_id)

            image = session.query(Image).filter(
                Image.id == image_id,
                Image.order_id == order_id # 해당 주문에 속한 이미지인지 확인
            ).first()

            if image:
                session.delete(image)
                session.commit()
                # 변경사항 반영을 위해 order 객체를 expire하거나 재조회 필요할 수 있음
                session.refresh(order) # 세션 내 객체 상태 갱신
            else:
                # 이미지가 없거나 해당 주문 소속이 아니면 예외 또는 특정 응답 처리 가능
                pass # 또는 ImageNotFoundError 등 발생

            return order


class NotFoundError(Exception):
    entity_name: str

    def __init__(self, entity_id):
        super().__init__(f"{self.entity_name} not found, id: {entity_id}")

class UserNotFoundError(NotFoundError):
    entity_name: str = "User"

class OrderNotFoundError(NotFoundError):
    entity_name: str = "Order"

class MinioRepository:
    def __init__(self, minio_client: Minio, bucket_name: str = "socialing") -> None:
        self.client = minio_client
        self.bucket_name = bucket_name

        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def list_objects(self, table_type: str, table_id: int) -> List[str]:
        prefix = f"{table_type}/{table_id}/"
        objects = self.client.list_objects(self.bucket_name, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]

    def get_presigned_url(self, object_key: str, expires: timedelta = timedelta(days=1)) -> str:
        try:
            stat = self.client.stat_object(self.bucket_name, object_key)
            content_type = stat.content_type
            response_headers = {'response-content-type': content_type}
            return self.client.presigned_get_object(
                self.bucket_name,
                object_key,
                expires=expires,
                response_headers=response_headers
            )
        except S3Error as e:
            raise ValueError(f"Failed to generate presigned URL: {str(e)}")

    def upload_file(self, file_data: BinaryIO, file_size: int, content_type: str, object_key: str) -> str:
        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_key,
                data=file_data,
                length=file_size,
                content_type=content_type
            )
            return object_key
        except S3Error as e:
            raise ValueError(f"Failed to upload file: {str(e)}")

    def delete_file(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket_name, object_key)
        except S3Error as e:
            raise ValueError(f"Failed to delete file: {str(e)}")

class ImageRepository:
    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def add_image(self, bucket: str, path: str, order_id: int = None) -> Image:
        with self.session_factory() as session:
            image = Image(bucket=bucket, path=path, order_id=order_id)
            session.add(image)
            session.commit()
            session.refresh(image)
            return image

    def get_image_by_id(self, image_id: int) -> Image:
        with self.session_factory() as session:
            return session.query(Image).filter(Image.id == image_id).first()

    def delete_image(self, image_id: int) -> bool:
        """주어진 ID의 이미지 레코드를 DB에서 삭제합니다."""
        with self.session_factory() as session:
            img = session.query(Image).filter(Image.id == image_id).first()
            if img:
                session.delete(img)
                session.commit()
                return True
            return False # 삭제할 이미지가 없음

    def delete_images_by_order(self, order_id: int) -> List[str]:
        """주어진 order_id에 해당하는 모든 이미지 레코드를 DB에서 삭제하고, 삭제된 파일 경로 리스트를 반환합니다."""
        deleted_paths = []
        with self.session_factory() as session:
            images = session.query(Image).filter(Image.order_id == order_id).all()
            if images:
                deleted_paths = [img.path for img in images] # 경로 먼저 저장
                for image in images:
                    session.delete(image)
                session.commit()
            return deleted_paths


class MainPageSettingRepository:
    """
    메인 페이지 설정을 관리하는 리포지토리.
    키-값 형태로 설정을 저장하고 조회합니다.
    """
    def __init__(self, session_factory: Callable[..., AbstractContextManager[Session]]) -> None:
        self.session_factory = session_factory

    def get_setting(self, key: str) -> Optional[Any]:
        """특정 설정 키의 값을 가져옵니다."""
        with self.session_factory() as session:
            setting = session.query(MainPageSetting.setting_value)\
                        .filter(MainPageSetting.setting_key == key)\
                        .scalar()
            return setting  # 예: 123 또는 [45, 67, 89]

    def upsert_setting(self, key: str, value: Any) -> None:
        """설정 키-값을 추가하거나 업데이트합니다 (UPSERT)."""
        with self.session_factory() as session:
            # 먼저 기존 설정이 있는지 확인
            existing = session.query(MainPageSetting)\
                        .filter(MainPageSetting.setting_key == key)\
                        .first()
            
            if existing:
                # 기존 설정이 있으면 업데이트
                existing.setting_value = value
            else:
                # 없으면 새로 생성
                new_setting = MainPageSetting(setting_key=key, setting_value=value)
                session.add(new_setting)
            
            session.commit()

    def delete_setting(self, key: str) -> bool:
        """특정 설정 키를 삭제합니다. 삭제된 경우 True를 반환합니다."""
        with self.session_factory() as session:
            result = session.query(MainPageSetting)\
                    .filter(MainPageSetting.setting_key == key)\
                    .delete()
            session.commit()
            return result > 0


class DocumentRepository:
    """Repository for managing documents in a MongoDB collection."""
    
    def __init__(self, get_collection: Callable[[str], Collection], collection_name: str) -> None:
        """
        MongoDB 컬렉션에 액세스하는 문서 리포지토리를 초기화합니다.
        
        Args:
            get_collection: 컬렉션 이름으로 컬렉션 객체를 반환하는 함수
            collection_name: 사용할 컬렉션 이름
        """
        self.get_collection = get_collection
        self.collection_name = collection_name
    
    @property
    def collection(self) -> Collection:
        """현재 리포지토리가 사용하는 컬렉션 객체를 반환합니다."""
        return self.get_collection(self.collection_name)
    
    def insert_one(self, document: Dict) -> Optional[str]:
        """컬렉션에 단일 문서를 삽입합니다."""
        try:
            # 생성 시간 추가
            if 'created_at' not in document:
                document['created_at'] = datetime.utcnow()
            
            result = self.collection.insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error inserting document into {self.collection_name}: {e}")
            return None
    
    def find_by_id(self, id: str) -> Optional[Dict]:
        """ID로 문서를 조회합니다."""
        try:
            result = self.collection.find_one({"_id": ObjectId(id)})
            if result and '_id' in result:
                result['_id'] = str(result['_id'])  # ObjectId를 문자열로 변환
            return result
        except Exception as e:
            logger.error(f"Error finding document by ID in {self.collection_name}: {e}")
            return None
    
    def find_many(self, filter_dict: Dict = None, 
                 sort: List = None, 
                 limit: int = 0, 
                 skip: int = 0) -> List[Dict]:
        """여러 문서를 조회합니다."""
        filter_dict = filter_dict or {}
        try:
            cursor = self.collection.find(filter_dict)
            
            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)
                
            results = list(cursor)
            
            # ObjectId를 문자열로 변환
            for result in results:
                if '_id' in result:
                    result['_id'] = str(result['_id'])
            return results
        except Exception as e:
            logger.error(f"Error finding documents in {self.collection_name}: {e}")
            return []
    
    def update_by_id(self, id: str, update_dict: Dict) -> Optional[int]:
        """ID로 문서를 업데이트합니다."""
        try:
            # 업데이트 시간 추가
            if '$set' in update_dict:
                update_dict['$set']['updated_at'] = datetime.utcnow()
            else:
                update_dict['$set'] = {'updated_at': datetime.utcnow()}
                
            result = self.collection.update_one(
                {"_id": ObjectId(id)}, 
                update_dict
            )
            return result.modified_count
        except Exception as e:
            logger.error(f"Error updating document in {self.collection_name}: {e}")
            return None
    
    def delete_by_id(self, id: str) -> Optional[int]:
        """ID로 문서를 삭제합니다."""
        try:
            result = self.collection.delete_one({"_id": ObjectId(id)})
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting document in {self.collection_name}: {e}")
            return None
    
    def count_documents(self, filter_dict: Dict = None) -> int:
        """문서 수를 계산합니다."""
        filter_dict = filter_dict or {}
        try:
            return self.collection.count_documents(filter_dict)
        except Exception as e:
            logger.error(f"Error counting documents in {self.collection_name}: {e}")
            return 0
