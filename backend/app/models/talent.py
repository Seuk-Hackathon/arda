"""Talent 컨텍스트 · 내부 사용자 (직원).

ADR-0035 Phase 2 · models.py 분할."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.constants import (
    ROLES,
    _in,
)

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None



# ── users — 내부 사용자 (A1·A2) ──────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # 비활성 계정은 로그인도 토큰 사용도 막힌다 (A4). 삭제 대신 이것을 쓴다 —
    # users.id 가 created_by·evaluator_id·assigned_by·changed_by 로 도처에 박혀
    # 있어서 물리 삭제는 이력을 부순다.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_users_role"),)


# ── 지원자 비밀번호 (2026-09-16, ADR-0033 개정) ──────────────────────
#
# **왜 `applications` 가 아니라 따로인가**: 비밀번호는 사람(이메일) 단위인데 지원은
# 여러 건이다. 지원서마다 두면 같은 사람이 공고 둘에 냈을 때 비밀번호가 두 벌 생기고,
# 한쪽에서 바꾸면 다른 쪽이 옛 것이 된다.
class ApplicantCredential(Base):
    """지원자 로그인 비밀번호. 없으면 아직 안 정한 것이다(생년월일로 들어온다)."""

    __tablename__ = "applicant_credentials"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApplicantPasswordToken(Base):
    """비밀번호 설정·재설정 링크. **원본은 메일 본문에만 있다.**

    조회 링크(일정·인적성·면접)는 평문으로 저장해도 새어 봐야 "내 지원 현황이
    보인다" 지만, **이 링크가 새면 계정이 통째로 넘어간다.** 무게가 달라서 회사
    API 키와 같은 방식(bcrypt 해시만 저장)으로 다룬다.

    이메일로 좁힌 뒤 그 안에서 대조한다 — 해시는 O(1) 조회가 안 된다.
    """

    __tablename__ = "applicant_password_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # 한 번 쓰면 죽는다. 지우지 않고 남기는 이유는 "이미 쓴 링크" 와 "없는 링크" 를
    # 서버가 구별해 로그로 볼 수 있어야 해서다 — 지원자에게는 같은 문구로 답한다.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
