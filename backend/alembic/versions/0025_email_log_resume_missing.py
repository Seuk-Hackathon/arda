"""email_logs.stage 에 resume_missing 허용 (ADR-0037 Phase B)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-17

회사 통합 API 로 온 이력서 URL 을 받지 못하면 지원자에게 안내 메일을 보낸다.
`password_setup`(0024)과 같은 기능성 메일이라 단계에도 `custom` 에도 안 붙는다.
0024 가 막았던 사고(제약이 INSERT 를 거부 → 백그라운드라 아무도 모름)를 되풀이하지
않도록 코드와 같은 커밋에 넣는다.
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_OLD = (
    "stage IN ('applied', 'screening', 'interview', 'accepted', 'rejected', "
    "'custom', 'password_setup')"
)
_NEW = (
    "stage IN ('applied', 'screening', 'interview', 'accepted', 'rejected', "
    "'custom', 'password_setup', 'resume_missing')"
)


def upgrade() -> None:
    op.drop_constraint("ck_email_logs_stage", "email_logs", type_="check")
    op.create_check_constraint("ck_email_logs_stage", "email_logs", _NEW)


def downgrade() -> None:
    # `resume_missing` 행이 있으면 제약이 안 걸린다 — 이력을 지우는 일이라 여기서
    # 하지 않는다(0024 와 같은 판단).
    op.drop_constraint("ck_email_logs_stage", "email_logs", type_="check")
    op.create_check_constraint("ck_email_logs_stage", "email_logs", _OLD)
