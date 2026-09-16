"""email_logs.stage 에 password_setup 허용 (ADR-0033 개정 후속)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-16

**운영에서 실제로 막혔다.** 비밀번호 설정 링크 메일을 보내려고 `email_logs` 행을
만드는데, `ck_email_logs_stage` 가 `applied·screening·interview·accepted·rejected·
custom` 만 허용해 **INSERT 가 거부됐다.** 백그라운드 작업이라 요청은 202 로 끝나고,
지원자는 메일을 영영 못 받는다(2026-09-16 실측).

`custom` 으로 적지 않는 이유는 그쪽이 "담당자가 직접 쓴 메일" 이라서다 — 통계에서
사람이 쓴 것과 시스템이 보낸 링크가 섞인다.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_OLD = "stage IN ('applied', 'screening', 'interview', 'accepted', 'rejected', 'custom')"
_NEW = (
    "stage IN ('applied', 'screening', 'interview', 'accepted', 'rejected', "
    "'custom', 'password_setup')"
)


def upgrade() -> None:
    op.drop_constraint("ck_email_logs_stage", "email_logs", type_="check")
    op.create_check_constraint("ck_email_logs_stage", "email_logs", _NEW)


def downgrade() -> None:
    # 되돌리기 전에 `password_setup` 행이 있으면 제약이 안 걸린다 — 그 행을 지우는
    # 것은 이력을 지우는 일이라 여기서 하지 않는다. 필요하면 사람이 판단한다.
    op.drop_constraint("ck_email_logs_stage", "email_logs", type_="check")
    op.create_check_constraint("ck_email_logs_stage", "email_logs", _OLD)
