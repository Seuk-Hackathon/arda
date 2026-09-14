"""회사 통합 API — integration_clients 테이블 + applications 흡수 필드

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-14

ADR-0037. 회사 시스템이 지원자를 Arda 로 push 하는 서버-투-서버 API 의 뒤판.

**신규 테이블 `integration_clients`**
- 회사가 발급받는 API key (bcrypt 해시)
- 회사 하나에 여러 key 가능 (rotation · 복수 시스템 연결)
- `revoked_at` 로 soft delete — 감사 용도로 남긴다

**applications 컬럼 추가**
- `external_id` — 회사 쪽 unique id (idempotency 키)
- `integration_client_id` — 어떤 통합으로 왔는지 · nullable (기존 form/manual 은 NULL)
- `source` CHECK 확대: form/manual + integration/email/saramin/jobkorea

**하위호환**: 옛 행은 `integration_client_id=NULL`, `external_id=NULL`. 옛 소스
"form"·"manual" 은 그대로 유효. 롤백 시 컬럼 제거 + CHECK 원복.
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


NEW_SOURCES = ("form", "manual", "integration", "email", "saramin", "jobkorea", "wanted")
OLD_SOURCES = ("form", "manual")


def upgrade() -> None:
    # 1. integration_clients 테이블
    op.create_table(
        "integration_clients",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "company_id",
            sa.BigInteger,
            sa.ForeignKey("company_profile.id"),
            nullable=False,
        ),
        # bcrypt 해시. 원본 api_key 는 발급 순간만 노출.
        sa.Column("api_key_hash", sa.Text, nullable=False, unique=True),
        # 관리 UI 표시용 · "arda_ak_abc12345" 8~16 자.
        sa.Column("api_key_prefix", sa.String(24), nullable=False),
        # "Workday 통합" 같은 별칭.
        sa.Column("name", sa.String(100), nullable=False),
        # (선택) 상태 변경 시 회사에 콜백.
        sa.Column("webhook_url", sa.String(500)),
        sa.Column("webhook_secret", sa.String(128)),
        sa.Column("rate_limit_per_minute", sa.Integer, nullable=False, server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # soft delete — 감사 용도로 행은 남긴다.
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        # 최근 API 사용 시각 · rate limit·유휴 감시.
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_integration_clients_company", "integration_clients", ["company_id"])
    # 활성 (revoked_at IS NULL) 만 인덱스 · 인증 조회가 이 인덱스 하나로.
    op.create_index(
        "ix_integration_clients_active_hash",
        "integration_clients",
        ["api_key_hash"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # 2. applications 컬럼 추가
    op.add_column(
        "applications",
        sa.Column("external_id", sa.String(200)),
    )
    op.add_column(
        "applications",
        sa.Column(
            "integration_client_id",
            sa.BigInteger,
            sa.ForeignKey("integration_clients.id"),
        ),
    )
    # 같은 통합에서 같은 external_id 두 번 못 옴 (idempotency 계약).
    op.create_unique_constraint(
        "uq_applications_integration_external",
        "applications",
        ["integration_client_id", "external_id"],
    )

    # 3. source CHECK 확대
    op.drop_constraint("ck_applications_source", "applications", type_="check")
    values = ", ".join(f"'{s}'" for s in NEW_SOURCES)
    op.create_check_constraint(
        "ck_applications_source",
        "applications",
        f"source IN ({values})",
    )


def downgrade() -> None:
    # source CHECK 원복 — integration 소스가 남아 있으면 다운그레이드가 실패한다.
    # 그때는 먼저 그 행들을 정리하고 다운그레이드 (또는 명시적으로 옛 값으로 갱신).
    op.drop_constraint("ck_applications_source", "applications", type_="check")
    values = ", ".join(f"'{s}'" for s in OLD_SOURCES)
    op.create_check_constraint(
        "ck_applications_source",
        "applications",
        f"source IN ({values})",
    )

    op.drop_constraint(
        "uq_applications_integration_external",
        "applications",
        type_="unique",
    )
    op.drop_column("applications", "integration_client_id")
    op.drop_column("applications", "external_id")

    op.drop_index("ix_integration_clients_active_hash", table_name="integration_clients")
    op.drop_index("ix_integration_clients_company", table_name="integration_clients")
    op.drop_table("integration_clients")
