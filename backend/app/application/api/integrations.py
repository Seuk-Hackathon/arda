"""회사 통합 API — 서버-투-서버 지원자 흡수 (ADR-0037).

회사 백엔드가 자기 시스템에서 새 지원자를 만들었을 때 Arda 로 push. 이 라우터가
그 진입점.

**핵심 계약**:
- 인증: `Authorization: Bearer <company_api_key>` (bcrypt 대조).
- Idempotent: 같은 `(integration_client_id, external_id)` 로 두 번 오면 기존 결과 반환.
- 이력서: `resume.base64` 는 즉시 저장 · `resume.url` 은 Phase B 에서 비동기 다운로드.

**후속 (Phase B)**:
- Rate limit 검사 (`rate_limit_per_minute`)
- Webhook 콜백 (상태 변경 시 회사 알림)
- Resume URL 비동기 다운로드 (n8n or worker)
- 관리 UI (API key 발급·회수)
- SDK (Python · Node.js) 예시
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status as http
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Application, IntegrationClient, JobPosting
from app.shared import s3

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


# ── Pydantic 스키마 ─────────────────────────────────────────────────────
class ApplicantPayload(BaseModel):
    """회사가 넘기는 지원자 필수 정보 4가지 + 생년월일 (ADR-0033 로그인용)."""

    name: str = Field(..., min_length=1, max_length=50)
    # 이메일은 간단한 regex 로만 본다 — 지원자 앱 로그인 (ADR-0033) 이 이메일 + 생년월일
    # 이라 형식이 맞아야 로그인이 된다. RFC 완전 검증까지는 필요 없음.
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    phone: str = Field(..., min_length=1, max_length=20)
    # YYYYMMDD 8자리. ADR-0033 지원자 앱 로그인 (이메일 + 생년월일).
    birth_date: str = Field(..., pattern=r"^(19|20)\d{6}$")


class ResumePayload(BaseModel):
    """이력서 · `url` 또는 `base64` 하나. url 은 Phase B 에서 비동기 다운로드."""

    url: str | None = Field(None, description="Arda 가 다운로드할 이력서 URL")
    base64: str | None = Field(None, description="파일 자체 (base64 encoded)")
    filename: str | None = Field(None, description="원본 파일명 (확장자 판정용)")


class IntegrationApplicationCreate(BaseModel):
    """회사 → Arda: 새 지원자 push 요청."""

    external_id: str = Field(..., min_length=1, max_length=200)
    posting_token: str = Field(..., min_length=1, max_length=64)
    applicant: ApplicantPayload
    resume: ResumePayload | None = None
    cover_letter: str | None = Field(None, max_length=10000)
    source: str = Field(
        "integration",
        description="유입 채널 태그 (integration · saramin · jobkorea · wanted 등)",
    )


class IntegrationApplicationResponse(BaseModel):
    arda_application_id: int
    status: str  # "received" (신규) · "duplicate" (idempotent 반환)
    public_url: str | None = None


# ── 인증 ────────────────────────────────────────────────────────────────
def _client_from_header(
    request: Request, db: Session = Depends(get_db)
) -> IntegrationClient:
    """`Authorization: Bearer <api_key>` 헤더로 통합 클라이언트를 찾아 반환.

    bcrypt 는 O(1) 조회가 불가능하므로 활성 key 를 순회하며 대조한다. 회사 수가
    수천 개 이하일 때는 충분 · 그 이상이면 Phase B 에서 prefix 로 좁힌다.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(http.HTTP_401_UNAUTHORIZED, "인증 헤더가 없습니다")
    provided = auth[len("Bearer ") :].encode("utf-8")

    # 활성 클라이언트만 · revoked 는 제외
    stmt = select(IntegrationClient).where(IntegrationClient.revoked_at.is_(None))
    for client in db.scalars(stmt).all():
        if bcrypt.checkpw(provided, client.api_key_hash.encode("utf-8")):
            client.last_used_at = datetime.now(UTC)
            db.commit()
            return client

    raise HTTPException(http.HTTP_401_UNAUTHORIZED, "잘못된 API key 입니다")


# ── 유틸 ────────────────────────────────────────────────────────────────
def _save_resume_from_base64(
    application_id: int, resume: ResumePayload
) -> str | None:
    """base64 로 온 이력서를 S3 에 저장하고 s3_key 반환."""
    if not resume.base64:
        return None
    try:
        blob = base64.b64decode(resume.base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            http.HTTP_422_UNPROCESSABLE_ENTITY, f"base64 해석 실패: {exc}"
        ) from exc

    ext = "pdf"  # 기본. Phase B 에서 MIME sniffing 개선.
    if resume.filename and "." in resume.filename:
        ext = resume.filename.rsplit(".", 1)[-1].lower()[:10]

    key = f"applications/{uuid.uuid4()}/resume.{ext}"
    try:
        s3._client().put_object(Bucket=s3.BUCKET, Key=key, Body=blob)
    except Exception as exc:  # noqa: BLE001
        logger.exception("이력서 S3 저장 실패 · application_id=%s", application_id)
        raise HTTPException(
            http.HTTP_502_BAD_GATEWAY, f"이력서 저장 실패: {exc}"
        ) from exc
    return key


# ── 엔드포인트 ──────────────────────────────────────────────────────────
@router.post(
    "/applications",
    response_model=IntegrationApplicationResponse,
    status_code=http.HTTP_201_CREATED,
)
def create_application_via_integration(
    payload: IntegrationApplicationCreate,
    client: IntegrationClient = Depends(_client_from_header),
    db: Session = Depends(get_db),
) -> IntegrationApplicationResponse:
    """회사가 자기 시스템의 새 지원자를 Arda 로 push. Idempotent.

    같은 `external_id` 로 재요청하면 최초 생성한 지원서를 그대로 돌려 준다 —
    회사 쪽 재시도(네트워크 오류)가 중복 지원을 만들지 않게 한다.
    """
    # 1. Idempotency 체크
    existing = db.scalar(
        select(Application).where(
            Application.integration_client_id == client.id,
            Application.external_id == payload.external_id,
        )
    )
    if existing is not None:
        return IntegrationApplicationResponse(
            arda_application_id=existing.id,
            status="duplicate",
            public_url=_public_url(existing),
        )

    # 2. 공고 확인
    posting = db.scalar(
        select(JobPosting).where(JobPosting.public_token == payload.posting_token)
    )
    if posting is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "공고를 찾을 수 없습니다")

    # 3. 생년월일 파싱 (YYYYMMDD → date)
    b = payload.applicant.birth_date
    try:
        birth = datetime.strptime(b, "%Y%m%d").date()
    except ValueError as exc:
        raise HTTPException(
            http.HTTP_422_UNPROCESSABLE_ENTITY, "birth_date 형식 오류 (YYYYMMDD)"
        ) from exc

    # 4. 지원서 생성 (트랜잭션 안에서)
    app_row = Application(
        job_posting_id=posting.id,
        name=payload.applicant.name,
        email=payload.applicant.email,
        phone=payload.applicant.phone,
        birth_date=birth,
        self_intro=payload.cover_letter,
        current_stage="applied",
        privacy_agreed_at=datetime.now(UTC),
        source=payload.source,
        external_id=payload.external_id,
        integration_client_id=client.id,
    )
    db.add(app_row)
    try:
        db.flush()  # id 를 채운다
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        # UNIQUE (integration_client_id, external_id) 재확인 (레이스 조건)
        existing = db.scalar(
            select(Application).where(
                Application.integration_client_id == client.id,
                Application.external_id == payload.external_id,
            )
        )
        if existing is not None:
            return IntegrationApplicationResponse(
                arda_application_id=existing.id,
                status="duplicate",
                public_url=_public_url(existing),
            )
        logger.exception("지원서 생성 실패")
        raise HTTPException(
            http.HTTP_500_INTERNAL_SERVER_ERROR, f"지원서 생성 실패: {exc}"
        ) from exc

    # 5. 이력서 저장 (base64 만 · url 은 Phase B 에서 비동기)
    if payload.resume and payload.resume.base64:
        _save_resume_from_base64(app_row.id, payload.resume)

    db.commit()
    logger.info(
        "통합 지원서 생성 · client=%s external=%s application=%s",
        client.name, payload.external_id, app_row.id,
    )

    return IntegrationApplicationResponse(
        arda_application_id=app_row.id,
        status="received",
        public_url=_public_url(app_row),
    )


def _public_url(app_row: Application) -> str | None:
    """지원자가 상태를 볼 수 있는 공개 URL. portal_token 이 없으면 None."""
    import os

    base = os.getenv("PUBLIC_APP_BASE_URL", "").rstrip("/")
    if not base or not app_row.portal_token:
        return None
    return f"{base}/my/{app_row.portal_token}"


# ── 관리자용 · API key 발급 (임시) ─────────────────────────────────────
# Phase B 에서 정식 관리 UI 로 옮긴다. 지금은 admin 만 쓰는 스크립트성 엔드포인트.
class IssueKeyRequest(BaseModel):
    company_id: int
    name: str = Field(..., max_length=100)


class IssueKeyResponse(BaseModel):
    api_key: str  # 원본 · 한 번만 노출
    api_key_prefix: str
    client_id: int


def _new_api_key() -> tuple[str, str]:
    """새 API key 생성. 원본 · prefix 반환."""
    body = secrets.token_urlsafe(32)
    raw = f"arda_ak_{body}"
    prefix = raw[:24]  # "arda_ak_" + 처음 16자
    return raw, prefix


@router.post(
    "/keys",
    response_model=IssueKeyResponse,
    status_code=http.HTTP_201_CREATED,
    # 관리자 인증은 Phase B 에서. 지금은 이 라우트 자체를 배포 후 삭제 or
    # feature flag 뒤에 두는 것 권장.
    include_in_schema=False,
)
def issue_key(
    payload: IssueKeyRequest, db: Session = Depends(get_db)
) -> IssueKeyResponse:
    """새 API key 발급. 관리 UI 완성 전 임시 endpoint."""
    raw, prefix = _new_api_key()
    hashed = bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    row = IntegrationClient(
        company_id=payload.company_id,
        api_key_hash=hashed,
        api_key_prefix=prefix,
        name=payload.name,
    )
    db.add(row)
    db.commit()
    logger.info("API key 발급 · client=%s prefix=%s", row.id, prefix)
    # 원본 key 는 이 응답 이후 다시 볼 수 없다 (해시만 저장).
    return IssueKeyResponse(api_key=raw, api_key_prefix=prefix, client_id=row.id)


# 임포트 순환 방지 · 실제 사용 시점에 hashlib 필요할 수 있음
__all__ = ["router"]

# SHA-256 fingerprint helper (Phase B 에서 audit 로그 용도)
def _sha256_fp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
