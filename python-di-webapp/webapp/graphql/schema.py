import strawberry
from strawberry.fastapi import GraphQLRouter
from typing import Optional, List

from .types import UserType, OrderType, DeletionResult
from .resolvers import (
    get_users_resolver,
    get_user_by_id_resolver,
    create_user_resolver,
    get_orders_resolver,
    create_order_resolver,
    get_order_by_id_resolver,
    delete_user_resolver,
    delete_profile_image_resolver,
    delete_order_resolver,
    delete_single_order_image_resolver,
    delete_all_order_images_resolver,
)

@strawberry.type
class Query:
    users: List[UserType] = strawberry.field(resolver=get_users_resolver)
    user: Optional[UserType] = strawberry.field(resolver=get_user_by_id_resolver)
    orders: List[OrderType] = strawberry.field(resolver=get_orders_resolver)
    order: Optional[OrderType] = strawberry.field(resolver=get_order_by_id_resolver)

@strawberry.type
class Mutation:
    create_user: UserType = strawberry.mutation(resolver=create_user_resolver)
    create_order: OrderType = strawberry.mutation(resolver=create_order_resolver)
    delete_user: DeletionResult = strawberry.mutation(resolver=delete_user_resolver)
    delete_profile_image: UserType = strawberry.mutation(resolver=delete_profile_image_resolver)
    delete_order: DeletionResult = strawberry.mutation(resolver=delete_order_resolver)
    delete_single_order_image: OrderType = strawberry.mutation(resolver=delete_single_order_image_resolver)
    delete_all_order_images: OrderType = strawberry.mutation(resolver=delete_all_order_images_resolver)
schema = strawberry.Schema(query=Query, mutation=Mutation)

# Info.context["user_service"], Info.context["order_service"]를 사용하기 위해
# GraphQLRouter 생성 시 context_fn에서 DI 컨테이너를 받아 context를 구성
def get_context():
    # 의존성(services)을 DI에서 가져오기
    from webapp.containers import Container
    container = Container()
    user_service = container.user_service()
    order_service = container.order_service()
    return {
        "user_service": user_service,
        "order_service": order_service
    }

graphql_app = GraphQLRouter(schema, context_getter=get_context)
