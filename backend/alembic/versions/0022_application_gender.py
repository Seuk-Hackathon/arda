"""applications.gender — 성별 (면접 프로필 불일치 감지용)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-15

면접 findings 시스템이 "저는 여자입니다" 같은 발언을 지원서 프로필과 대조하기 위한 칸.
값: male | female | other | NULL(미입력).
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("gender", sa.String(10), nullable=True))
    op.create_check_constraint(
        "ck_applications_gender",
        "applications",
        "gender IS NULL OR gender IN ('male', 'female', 'other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_applications_gender", "applications", type_="check")
    op.drop_column("applications", "gender")
