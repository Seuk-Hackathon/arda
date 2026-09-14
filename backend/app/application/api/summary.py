"""종합 평가 · 공고별 지원자 점수 + 요약 (2026-09-14).

담당자용 요약 화면 (`/summary`) 이 한 번에 그리는 데이터. **여러 API 를 조합하지
않고 한 번에 준다** — 대시보드성 화면이라 정보 조각이 화면당 수십 개다. 각 조각에
대해 별도 요청을 보내면 열 때마다 브라우저가 스무 개 요청을 뿌린다.

**계산은 여기서 안 한다** — screening.final_score · grade 는 이미 순수 함수라
그대로 재사용. 이 엔드포인트는 조립만 담당.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapter.outbound.pg.interview_pg_repository import PgInterviewRepository
from app.application import screening
from app.db import get_db
from app.deps import get_current_user
from app.models import Application, JobPosting, User
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/v1/summary", tags=["summary"])


class ApplicantSummary(BaseModel):
    """공고 아래 지원자 한 명의 요약. 종합 점수·등급이 이 뷰의 핵심 컬럼."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    current_stage: str
    ai_summary: str | None = None

    # 자동 심사 · 면접 점수 · 종합
    doc_score: int | None = None
    doc_decision: str | None = None
    interview_ai_score: int | None = None
    final_score: float | None = None
    grade: str | None = None

    # 면접 요약 · 우려사항 (상위 뷰에서 드릴다운)
    concerns: list[str] = []
    strengths: list[str] = []


class PostingSummary(BaseModel):
    """공고 하나 + 그 아래 지원자들."""

    id: int
    title: str
    status: str
    applicant_count: int
    applicants: list[ApplicantSummary]


@router.get("", response_model=list[PostingSummary])
def get_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """공고별 지원자 종합 평가.

    각 공고 아래에 지원자 목록 · 서류 · 면접 점수 · 종합 등급 · 요약을 함께 준다.
    """
    postings = db.scalars(
        select(JobPosting).order_by(JobPosting.created_at.desc())
    ).all()

    interview_repo = PgInterviewRepository(db)
    weights = screening.weights(db)

    out: list[PostingSummary] = []
    for posting in postings:
        applications = db.scalars(
            select(Application)
            .where(Application.job_posting_id == posting.id)
            .order_by(Application.created_at.desc())
        ).all()

        applicants: list[ApplicantSummary] = []
        for app_row in applications:
            interview_ai = interview_repo.latest_ai_score_for_application(app_row.id)
            interview_detail = interview_repo.latest_ai_score_detail_for_application(app_row.id)
            final = screening.final_score(app_row.doc_score, interview_ai, weights)
            grade = screening.grade(final)

            concerns: list[str] = []
            strengths: list[str] = []
            if isinstance(interview_detail, dict):
                concerns = list(interview_detail.get("concerns") or [])[:3]
                strengths = list(interview_detail.get("strengths") or [])[:3]

            applicants.append(
                ApplicantSummary(
                    id=app_row.id,
                    name=app_row.name,
                    email=app_row.email,
                    current_stage=app_row.current_stage,
                    ai_summary=app_row.ai_summary,
                    doc_score=app_row.doc_score,
                    doc_decision=app_row.doc_decision,
                    interview_ai_score=interview_ai,
                    final_score=final,
                    grade=grade,
                    concerns=concerns,
                    strengths=strengths,
                )
            )

        out.append(
            PostingSummary(
                id=posting.id,
                title=posting.title,
                status=posting.status,
                applicant_count=len(applicants),
                applicants=applicants,
            )
        )

    return out
