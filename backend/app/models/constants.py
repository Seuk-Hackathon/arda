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

# 단계 메일 + `custom`(담당자 수동 발송) + `password_setup`.
#
# `password_setup` 은 **단계가 아니라 기능성 메일**이다 (2026-09-16, ADR-0033 개정).
# 지원자가 비밀번호 설정 링크를 받는 자리라 어느 전형 단계에도 안 붙는다. `custom`
# 으로 적지 않는 이유는 그쪽이 "담당자가 직접 쓴 메일" 을 뜻해서다 — 통계에서
# 사람이 쓴 것과 시스템이 보낸 링크가 섞인다.
#
# `resume_missing` 도 같은 부류다 (2026-09-17, ADR-0037 Phase B). 회사 통합 API 로 온
# 이력서 URL 을 받지 못했다고 지원자에게 알리는 메일.
EMAIL_LOG_STAGES = STAGES + ("custom", "password_setup", "resume_missing")
EMAIL_ACTOR_KINDS = ("human", "agent", "system")
TEMPLATE_STAGES = ("applied", "interview", "accepted", "rejected")


def _in(column: str, values: tuple[str, ...]) -> str:
    """체크 제약 문구를 만든다. 예: role IN ('admin', 'member')"""
    joined = ", ".join("'" + v + "'" for v in values)
    return column + " IN (" + joined + ")"
