"""지원자 비밀번호 로그인 — 자격 · 설정 링크 토큰 (ADR-0033 개정)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-16

지원자 로그인이 **이메일 + 생년월일 8자리**였다(ADR-0033). 그 ADR 이 스스로 적어
둔 약점이 그대로 이유다 — 경우의 수가 만 단위고, **새어도 바꿀 수 없는 값**이다.
게다가 지원 폼에서 생년월일이 선택이라 그 칸을 비운 사람은 영영 못 들어온다.

두 테이블을 만든다.

- `applicant_credentials` — 비밀번호. **이메일 단위**다. 지원서마다 두면 같은
  사람이 공고 둘에 냈을 때 비밀번호가 두 벌 생기고 한쪽만 바뀐다.
- `applicant_password_tokens` — 설정·재설정 링크. **해시만 저장**한다. 조회
  링크가 새면 "현황이 보인다" 지만 이 링크가 새면 계정이 넘어간다 — 회사 API
  키와 같은 무게로 다룬다(`integration_clients.api_key_hash` 와 같은 방식).
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applicant_credentials",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "applicant_password_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # 해시는 O(1) 조회가 안 된다. 이메일로 좁힌 뒤 그 안에서 대조한다.
    op.create_index(
        "ix_applicant_password_tokens_email", "applicant_password_tokens", ["email"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_applicant_password_tokens_email", table_name="applicant_password_tokens"
    )
    op.drop_table("applicant_password_tokens")
    op.drop_table("applicant_credentials")
