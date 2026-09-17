"""회사 통합 API — 서버-투-서버 지원자 흡수 (ADR-0037).

회사 백엔드가 자기 시스템에서 새 지원자를 만들었을 때 Arda 로 push. 이 라우터가
그 진입점.

**핵심 계약**:
- 인증: `Authorization: Bearer <company_api_key>` (bcrypt 대조).
- Idempotent: 같은 `(integration_client_id, external_id)` 로 두 번 오면 기존 결과 반환.
- 이력서: `resume.base64` 는 응답 전에 저장 · `resume.url` 은 응답 뒤 백그라운드에서
  받는다(`app/application/resume_fetch.py` — 2026-09-17 Phase B). 어느 쪽이든 지원
  폼과 같은 `files` 행이 되고, 그 뒤 요약·앵커가 돈다. **URL 을 못 받으면 요약을
  돌리지 않는다** — 자동 심사(ADR-0034)가 이력서 없는 지원서를 떨어뜨리지 않게.
- 같은 `external_id` 로 다시 오면서 이력서가 아직 없으면 **그때 다시 받는다.**
  회사 쪽 재전송이 곧 재시도 경로다.

**후속**:
- Rate limit 검사 (`rate_limit_per_minute`)
- Webhook 콜백 (상태 변경 시 회사 알림)
- 관리 UI (API key 발급·회수)
- SDK (Python · Node.js) 예시
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import secrets
from datetime import UTC, datetime

import bcrypt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status as http,
)
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application import resume_fetch
from app.db import get_db
from app.deps import require_roles
from app.models import Application, IntegrationClient, JobPosting, StageHistory, User
from app.shared.api.files import MAX_BYTES

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
    """이력서 · `url` 또는 `base64` **정확히 하나**."""

    url: str | None = Field(
        None, max_length=resume_fetch.MAX_URL_LEN,
        description="Arda 가 내려받을 이력서 URL (http·https, 80·443)",
    )
    # 10MB 를 base64 로 싸면 4/3 배. 그보다 긴 문자열은 풀기 전에 막는다
    base64: str | None = Field(
        None, max_length=MAX_BYTES * 4 // 3 + 4,
        description="파일 자체 (base64 encoded)",
    )
    filename: str | None = Field(None, max_length=255, description="원본 파일명")

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.url is None) == (self.base64 is None):
            raise ValueError("resume 은 url 과 base64 중 정확히 하나만 보낸다")
        return self


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


# ── 이력서 ──────────────────────────────────────────────────────────────
def _decode_base64(resume: ResumePayload) -> resume_fetch.Fetched:
    """base64 로 온 이력서를 풀고 **지원 폼과 같은 규격**으로 본다.

    Phase A 는 확장자를 파일명에서 믿고, 크기를 안 보고, 올린 키를 `files` 에 남기지
    않았다 — S3 에는 올라가는데 담당자 화면에는 이력서가 없었다(2026-09-17 발견).
    """
    try:
        blob = base64.b64decode(resume.base64 or "", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            http.HTTP_422_UNPROCESSABLE_ENTITY, "resume.base64 를 풀 수 없습니다"
        ) from exc
    if not blob:
        raise HTTPException(http.HTTP_422_UNPROCESSABLE_ENTITY, "이력서 파일이 비었습니다")
    if len(blob) > MAX_BYTES:
        raise HTTPException(
            http.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"이력서는 {MAX_BYTES // 1024 // 1024}MB 이하만 받습니다",
        )
    ext = resume_fetch.sniff(blob)
    if ext is None:
        raise HTTPException(
            http.HTTP_422_UNPROCESSABLE_ENTITY,
            "이력서는 PDF·DOCX·HWP·HWPX 만 받습니다",
        )
    return resume_fetch.Fetched(
        data=blob, ext=ext, filename=resume_fetch.safe_filename(resume.filename, ext)
    )


def _find_existing(db: Session, client_id: int, external_id: str):
    return db.scalar(
        select(Application).where(
            Application.integration_client_id == client_id,
            Application.external_id == external_id,
        )
    )


def _duplicate(
    db: Session, existing: Application, payload: IntegrationApplicationCreate,
    bg: BackgroundTasks,
) -> IntegrationApplicationResponse:
    """이미 받은 지원서. **이력서가 아직 없으면 이번에 온 것으로 다시 시도한다.**

    URL 을 못 받았을 때 회사가 할 수 있는 일은 같은 요청을 다시 보내는 것뿐이다.
    그걸 "이미 있음" 으로만 돌려보내면 그 지원자는 영영 이력서 없이 남는다.
    지원자 정보는 바꾸지 않는다 — 이력서 칸만 채운다.
    """
    resume = payload.resume
    if resume is not None and not resume_fetch.has_resume(db, existing.id):
        if resume.url:
            bg.add_task(resume_fetch.fetch_resume_bg, existing.id, resume.url)
        else:
            _store_or_502(db, existing.id, _decode_base64(resume))
            db.commit()
            bg.add_task(resume_fetch.after_resume, existing.id)
    return IntegrationApplicationResponse(
        arda_application_id=existing.id,
        status="duplicate",
        public_url=_public_url(existing),
    )


def _store_or_502(db: Session, application_id: int, fetched: resume_fetch.Fetched) -> None:
    try:
        resume_fetch.store(db, application_id, fetched)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("이력서 S3 저장 실패 · application_id=%s", application_id)
        # 지원서도 같이 롤백됐다. 회사가 같은 external_id 로 다시 보내면 된다
        raise HTTPException(http.HTTP_502_BAD_GATEWAY, "이력서 저장에 실패했습니다") from exc


# ── 엔드포인트 ──────────────────────────────────────────────────────────
@router.post(
    "/applications",
    response_model=IntegrationApplicationResponse,
    status_code=http.HTTP_201_CREATED,
)
def create_application_via_integration(
    payload: IntegrationApplicationCreate,
    bg: BackgroundTasks,
    client: IntegrationClient = Depends(_client_from_header),
    db: Session = Depends(get_db),
) -> IntegrationApplicationResponse:
    """회사가 자기 시스템의 새 지원자를 Arda 로 push. Idempotent.

    같은 `external_id` 로 재요청하면 최초 생성한 지원서를 그대로 돌려 준다 —
    회사 쪽 재시도(네트워크 오류)가 중복 지원을 만들지 않게 한다.
    """
    # 롤백 뒤에는 ORM 객체를 다시 읽어야 한다 — 먼저 값으로 잡아 둔다
    client_id = client.id

    # 1. Idempotency 체크
    existing = _find_existing(db, client_id, payload.external_id)
    if existing is not None:
        return _duplicate(db, existing, payload, bg)

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

    # 4. base64 이력서는 **지원서를 만들기 전에** 본다 — 규격 밖이면 아무것도 안 남긴다
    inline = None
    if payload.resume is not None and payload.resume.base64 is not None:
        inline = _decode_base64(payload.resume)

    # 5. 지원서 생성 (트랜잭션 안에서)
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
        integration_client_id=client_id,
    )
    db.add(app_row)
    try:
        db.flush()  # id 를 채운다
    except IntegrityError as exc:
        db.rollback()
        # UNIQUE (integration_client_id, external_id) 재확인 (레이스 조건)
        existing = _find_existing(db, client_id, payload.external_id)
        if existing is not None:
            return _duplicate(db, existing, payload, bg)
        # 남은 것은 UNIQUE(job_posting_id, email) — 지원 폼과 같은 409.
        # DB 오류 문구는 내보내지 않는다(제약 이름·값이 그대로 실린다)
        raise HTTPException(
            http.HTTP_409_CONFLICT, "이 이메일로 이미 이 공고에 지원했습니다"
        ) from exc

    # D5 — 접수도 이력이다. 폼 접수와 같이 changed_by 는 NULL(시스템)
    db.add(StageHistory(application_id=app_row.id, from_stage=None, to_stage="applied"))

    # 6. base64 는 같은 트랜잭션에 `files` 행까지 넣는다
    if inline is not None:
        _store_or_502(db, app_row.id, inline)

    db.commit()
    logger.info(
        "통합 지원서 생성 · client=%s external=%s application=%s resume=%s",
        client_id, payload.external_id, app_row.id,
        "url" if payload.resume and payload.resume.url else ("inline" if inline else "none"),
    )

    # 7. 뒤에서 돌 것. URL 은 받은 뒤에 요약·앵커가 이어지고, 못 받으면 안내 메일만
    if payload.resume is not None and payload.resume.url is not None:
        bg.add_task(resume_fetch.fetch_resume_bg, app_row.id, payload.resume.url)
    else:
        bg.add_task(resume_fetch.after_resume, app_row.id)

    return IntegrationApplicationResponse(
        arda_application_id=app_row.id,
        status="received",
        public_url=_public_url(app_row),
    )




def _public_url(app_row: Application) -> str | None:
    """지원자가 자기 지원 현황을 보는 주소 (2026-09-16 개정).

    예전에는 `/my/<portal_token>` 이었다. **그 토큰은 이제 아무 데도 안 쓰인다** —
    메일 링크 포털을 철거했고([ADR-0033](../../../../docs/03_decision/0033-지원자-앱-로그인.md)
    개정), 프론트에도 토큰을 읽는 화면이 없어 링크를 열면 그냥 로그인 화면이었다.

    지금은 **로그인 주소**를 준다. 지원자는 접수 메일로 받은 설정 링크에서
    비밀번호를 정하고 여기서 들어온다. 회사 쪽에서 볼 때 달라지는 것은 없다 —
    여전히 "지원자에게 알려 줄 주소" 하나다.
    """
    import os

    base = os.getenv("PUBLIC_APP_BASE_URL", "").rstrip("/")
    if not base:
        return None
    return f"{base}/my"


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
    include_in_schema=False,
)
def issue_key(
    payload: IssueKeyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
) -> IssueKeyResponse:
    """새 API key 발급. 관리 UI 완성 전 임시 endpoint — **admin 전용**.

    2026-09-17 까지 인증이 없었다. `include_in_schema=False` 는 문서에서 숨길 뿐
    막지 않는다 — 운영에서 토큰 없이 POST 하면 401 이 아니라 422(본문 검증)까지
    들어갔다. 본문만 맞추면 누구든 키를 받아 지원자를 밀어 넣을 수 있었고, 그
    지원자마다 요약·자동 심사(LLM)가 돈다.
    """
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
    logger.info(
        "API key 발급 · client=%s prefix=%s by=%s", row.id, prefix, admin.id
    )
    # 원본 key 는 이 응답 이후 다시 볼 수 없다 (해시만 저장).
    return IssueKeyResponse(api_key=raw, api_key_prefix=prefix, client_id=row.id)


# 임포트 순환 방지 · 실제 사용 시점에 hashlib 필요할 수 있음
__all__ = ["router"]

# SHA-256 fingerprint helper (Phase B 에서 audit 로그 용도)
def _sha256_fp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
