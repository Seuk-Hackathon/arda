"""지원자 비밀번호 — 설정 링크 발급·검증·저장 (2026-09-16, ADR-0033 개정).

지원자 로그인이 **이메일 + 생년월일 8자리**였다. 그 ADR 이 스스로 적어 둔 약점이
그대로 이유다 — 경우의 수가 만 단위고, **새어도 바꿀 수 없는 값**이다. 게다가 지원
폼에서 생년월일이 선택이라 그 칸을 비운 사람은 영영 로그인할 수 없었다.

## 링크를 조회 링크와 다르게 다루는 이유

일정·인적성·면접 링크는 평문으로 저장한다. 새어 봐야 "내 지원 현황이 보인다" 다.
**이 링크가 새면 계정이 통째로 넘어간다.** 그래서 회사 API 키와 같은 방식으로
다룬다 — **해시만 저장**하고 원본은 메일 본문에만 둔다.

해시는 O(1) 조회가 안 되므로 이메일로 좁힌 뒤 그 안에서 대조한다
(`integration_clients` 가 회사별로 순회하는 것과 같은 모양).
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicantCredential, ApplicantPasswordToken

logger = logging.getLogger(__name__)

# 링크 유효 기간. 포털 토큰(7일)과 같은 감각이다.
#
# **기한보다 재발급 길이 중요하다.** 짧으면(24시간) 접수 직후엔 비밀번호를 만들
# 동기가 없어 대부분 만료되고, 길면(30일+) 몇 주 뒤 메일함이 털렸을 때 계정이
# 넘어간다. 로그인 화면에 「설정 링크 다시 받기」가 있으면 짧게 가도 막히지 않는다.
TOKEN_DAYS = int(os.getenv("APPLICANT_PASSWORD_TOKEN_DAYS", "7"))

# bcrypt 는 **72 바이트를 넘는 입력을 말없이 자른다.** 한글은 글자당 3 바이트라
# 25자부터는 뒤를 무엇으로 치든 같은 비밀번호가 된다. 자르는 쪽이 더 나쁘다 —
# 사용자는 자기가 정한 것과 다른 값이 저장된 줄 모른다.
MAX_PASSWORD_BYTES = 72

PUBLIC_APP_BASE_URL = os.getenv("PUBLIC_APP_BASE_URL", "").rstrip("/")


def normalize(email: str) -> str:
    return email.strip().lower()


def setup_url(token: str) -> str:
    """지원자에게 줄 주소. **서버가 조립한다** — 화면이 조립하면 메일과 갈린다."""
    return f"{PUBLIC_APP_BASE_URL}/set-password/{token}"


def issue_token(db: Session, email: str) -> str:
    """설정 링크 토큰을 새로 발급한다. **그 이메일의 이전 토큰은 그 자리에서 죽는다.**

    원본을 돌려주고 DB 에는 해시만 남긴다 — 로그·응답 어디에도 원본을 남기지 않는다.
    """
    email = normalize(email)
    now = datetime.now(timezone.utc)

    # 재발급하면 이전 것은 무효 (포털 토큰이 이미 쓰는 규칙). 링크가 여러 장
    # 살아 있으면 오래된 메일에서 누른 것도 먹는다.
    for row in db.scalars(
        select(ApplicantPasswordToken).where(
            ApplicantPasswordToken.email == email,
            ApplicantPasswordToken.used_at.is_(None),
        )
    ).all():
        row.used_at = now

    raw = secrets.token_urlsafe(32)
    db.add(
        ApplicantPasswordToken(
            email=email,
            token_hash=bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode(),
            expires_at=now + timedelta(days=TOKEN_DAYS),
        )
    )
    db.flush()
    # **원본을 로그에 남기지 않는다** (회사 API 키가 prefix 만 남기는 것과 같다).
    logger.info("비밀번호 설정 링크 발급: domain=%s", email.rpartition("@")[2])
    return raw


def resolve_token(db: Session, raw: str) -> ApplicantPasswordToken | None:
    """살아 있는 토큰이면 그 행, 아니면 None.

    **만료와 사용됨을 구별해 돌려주지 않는다.** 부르는 쪽이 한 문구로 답해야
    토큰 유효성을 떠보는 도구가 되지 않는다 (로그인이 쓰는 원칙과 같다).
    """
    if not raw:
        return None
    now = datetime.now(timezone.utc)
    # 이메일을 모르는 채로 들어오므로 살아 있는 것만 훑는다. 만료·사용된 것은
    # 대조 대상에서 빠져 순회가 짧게 유지된다.
    rows = db.scalars(
        select(ApplicantPasswordToken).where(
            ApplicantPasswordToken.used_at.is_(None),
            ApplicantPasswordToken.expires_at > now,
        )
    ).all()
    for row in rows:
        if bcrypt.checkpw(raw.encode(), row.token_hash.encode()):
            return row
    return None


def too_long(password: str) -> bool:
    return len(password.encode("utf-8")) > MAX_PASSWORD_BYTES


def set_password(db: Session, token: ApplicantPasswordToken, password: str) -> None:
    """비밀번호를 저장하고 그 링크를 죽인다. 같은 이메일의 다른 링크도 같이 죽인다."""
    now = datetime.now(timezone.utc)
    cred = db.get(ApplicantCredential, token.email)
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    if cred is None:
        db.add(ApplicantCredential(email=token.email, password_hash=hashed))
    else:
        cred.password_hash = hashed
        cred.updated_at = now

    token.used_at = now
    for row in db.scalars(
        select(ApplicantPasswordToken).where(
            ApplicantPasswordToken.email == token.email,
            ApplicantPasswordToken.used_at.is_(None),
        )
    ).all():
        row.used_at = now
    db.commit()


def has_password(db: Session, email: str) -> bool:
    return db.get(ApplicantCredential, normalize(email)) is not None


def verify(db: Session, email: str, password: str) -> bool:
    cred = db.get(ApplicantCredential, normalize(email))
    if cred is None:
        return False
    try:
        return bcrypt.checkpw(password.encode(), cred.password_hash.encode())
    except ValueError:
        # 저장된 해시가 깨진 경우. 통과시키지 않는다.
        return False
