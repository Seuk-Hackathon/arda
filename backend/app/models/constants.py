"""도메인 상수 · 체크 제약 · enum 대체.

단계·역할 같은 고정값은 DB enum 이 아니라 **체크 제약 + 아래 상수**로 관리한다
(01-erd.md "단계(stage) — 고정 enum" 참고. 값이 늘어도 마이그레이션이 필요 없다).
"""

from __future__ import annotations

STAGES = ("applied", "screening", "interview", "accepted", "rejected")
SCREENING_MODES = ("auto", "manual")
DOC_DECISIONS = ("pass", "reject", "hold")
DECISION_SOURCES = ("agent", "human")
ROLES = ("admin", "member")
POSTING_STATUSES = ("draft", "open", "closed")
# 2026-09-14 (ADR-0037): 회사 통합 API 흡수 경로를 위한 값 추가.
# - integration: 서버-투-서버 API push (회사 백엔드)
# - email: 이메일 파싱 인입 (n8n)
# - saramin/jobkorea/wanted: 잡보드 어댑터
APPLICATION_SOURCES = (
    "form", "manual",
    "integration", "email", "saramin", "jobkorea", "wanted",
)
FILE_KINDS = ("resume", "cover_letter")
GENDERS = ("male", "female", "other")
EMAIL_STATUSES = ("queued", "sent", "failed")
PROPOSAL_STATUSES = ("proposed", "confirmed", "expired", "canceled")
DOC_TYPES = FILE_KINDS + ("self_intro",)
PUBLICATION_STATUSES = ("pending", "confirmed", "failed")

EMAIL_LOG_STAGES = STAGES + ("custom",)
EMAIL_ACTOR_KINDS = ("human", "agent", "system")
TEMPLATE_STAGES = ("applied", "interview", "accepted", "rejected")


def _in(column: str, values: tuple[str, ...]) -> str:
    """체크 제약 문구를 만든다. 예: role IN ('admin', 'member')"""
    joined = ", ".join("'" + v + "'" for v in values)
    return column + " IN (" + joined + ")"
