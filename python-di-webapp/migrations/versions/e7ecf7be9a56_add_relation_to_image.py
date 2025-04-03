"""Add Relation to image

Revision ID: e7ecf7be9a56
Revises: 29c055103f45
Create Date: 2025-04-02 12:31:15.065815

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7ecf7be9a56'
down_revision: Union[str, None] = '29c055103f45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('images', sa.Column('order_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'images', 'orders', ['order_id'], ['id'])
    # ### end Alembic commands ###

    # orders 테이블의 order_image_list 컬럼에서 이미지 ID 정보를 가져와서,
    # images 테이블의 order_id 컬럼을 채웁니다.
    connection = op.get_bind()
    results = connection.execute(
        sa.text("SELECT id, order_image_list FROM orders")
    ).mappings().all()  # .mappings()를 사용하여 dict 형태로 변환

    for row in results:
        order_id = row["id"]
        image_ids = row["order_image_list"]
        if image_ids:
            for image_id in image_ids:
                connection.execute(
                    sa.text("""
                        UPDATE images
                        SET order_id = :order_id
                        WHERE id = :image_id
                    """),
                    {"order_id": order_id, "image_id": image_id}
                )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'images', type_='foreignkey')
    op.drop_column('images', 'order_id')
    # ### end Alembic commands ###
