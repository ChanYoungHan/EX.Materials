from enum import Enum

class PathHelper:
    @staticmethod
    def generate_user_profile_path(user_id: int, image_id: int, original_filename: str) -> str:
        """
        사용자 프로필 이미지 경로 생성.
        예: "users/profile/{user_id}/{image_id}_{original_filename}"
        """
        return f"users/profile/{user_id}/{image_id}_{original_filename}"

    @staticmethod
    def generate_order_image_path(order_id: int, image_id: int, original_filename: str) -> str:
        """
        주문 이미지 경로 생성.
        예: "orders/{order_id}/{image_id}_{original_filename}"
        """
        return f"orders/{order_id}/{image_id}_{original_filename}"

class TableType(Enum):
    USER_PROFILE = "users/profile"
    ORDER = "orders"
