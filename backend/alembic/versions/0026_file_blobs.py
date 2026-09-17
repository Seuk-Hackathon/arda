"""file_blobs — 이력서 파일 본문을 DB 안에 둔다 (온프레미스 심사용, 2026-09-17)

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-17

> **번호 충돌 복구 (2026-09-17, woojeongalex).** #282 에서 이 파일은 `0023`(Revises
> 0022)으로 들어왔는데, `0023` 은 이미 `0023_applicant_password.py`(09-16)가 쓰고
> 있었다. alembic 은 경고만 내고 한쪽을 고르므로 **AWS 운영 DB(이미 0024)에서는
> 이 테이블이 영영 안 만들어지고**, 다운로드(`files.py` 가 매번 `file_blobs` 를
> 조회)가 전부 500 이 된다. 그래서 맨 뒤(0026)로 옮겼다.
>
> 옛 번호로 **이미 이 파일을 실행한 환경**(온프레미스 심사 서버)도 있을 수 있다.
> 그 환경은 반대로 `applicant_*` 두 테이블이 빠졌을 수 있다. 그래서 여기서는
> **없을 때만 만든다** — 둘 다. 어느 쪽 환경이든 `alembic upgrade head` 한 줄로
> 같은 모양이 된다.

**왜 DB 에 두나 (설계 반전이라 사연이 필요)**: 원래 이력서는 S3/MinIO 에 두고
브라우저가 presigned URL 로 직접 내려받는다 — 서버가 파일 바이트를 안 지나가게
하려던 것이다(shared/s3.py 머리말). AWS 에서는 서명 도메인이 브라우저가 볼 수
있는 실제 S3 이라 이 방식이 정말 통했다.

온프레미스는 사정이 다르다. MinIO 가 컨테이너 안에만 있어서 발급되는 URL
호스트가 `minio:9000` 이다. 이걸 브라우저에 그대로 던지면 이름이 안 풀려
다운로드 자체가 안 된다 (2026-09-17 담당자 화면 이력서 열기 실패로 확인).
MinIO 를 별도 서브도메인으로 노출하는 방법도 있었지만 심사(09-20~10-17) 동안
관리 지점을 하나 더 두지 않으려고 **파일을 그냥 DB 에 넣기로** 했다 (사용자 결정,
09-17 아침). 다운로드는 백엔드가 티켓 검사 후 스트리밍한다(shared/api/files.py).

파일 개수·크기: 심사에 쓰는 지원자 24명 x 이력서·자소서 2개 = 48개, 각 100KB
안팎. Postgres bytea 로 감당 되는 규모. 심사 뒤 개발 계속하는 AWS(seuk) 쪽은
이 테이블이 비어 있고 기존 S3 presign 경로가 계속 살아 있다 — 다운로드 코드가
`file_blobs` 존재 여부로 갈린다.

내리기: 데이터 손실이라 정확히 이 테이블 없을 때만 안전.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _applicant_password_upgrade():
    """`0023_applicant_password.upgrade` 를 그대로 빌려 온다 — 정의를 두 벌 두지 않는다."""
    path = Path(__file__).with_name("0023_applicant_password.py")
    spec = importlib.util.spec_from_file_location("_rev0023_applicant_password", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.upgrade


def upgrade() -> None:
    # 옛 번호(0023)로 file_blobs 만 실행되고 applicant_* 가 빠진 환경을 메운다.
    # 두 테이블은 한 리비전에서 같이 생기므로 하나만 있는 경우는 없다.
    if not _has("applicant_credentials"):
        _applicant_password_upgrade()()

    if _has("file_blobs"):
        return  # 옛 번호로 이미 만들어진 환경

    # file_id 를 PK 로 쓰면 파일 1개 = 블롭 1개(1:1). files 가 지워지면 블롭도
    # CASCADE 로 같이 지워야 한다 — 파일 메타만 지워지고 몇 MB 짜리 바이트가
    # 남으면 원인 모를 용량 증가로 이어진다.
    op.create_table(
        "file_blobs",
        sa.Column(
            "file_id",
            sa.BigInteger,
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content", sa.LargeBinary, nullable=False),
        # size_bytes 는 files 에도 있지만 여기서도 검증용으로 둔다 — 이관 스크립트가
        # 다른 값을 넣으면 즉시 눈에 띈다.
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        # sha256 = 이관·재이관 멱등성. 같은 키를 두 번 넣어도 값이 같으면 무해.
        # 64자 hex 로 고정.
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    # applicant_* 는 0023 의 몫이라 여기서 지우지 않는다.
    op.drop_table("file_blobs")
