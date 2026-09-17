"""n8n 워크플로 전용 내부 API — /internal/email-logs/{id}/render · /result.

인증(서비스 토큰), 렌더, 결과 기록의 멱등성 을 검증한다. 실제 SES·SMTP 호출은
없다 — 이 API 는 데이터 층만 만진다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import (
    Application,
    EmailLog,
    InterviewSession,
    InterviewTurn,
    JobPosting,
    User,
)


@pytest.fixture()
def client(db: Session, monkeypatch) -> TestClient:
    """서비스 토큰만 세팅한 클라이언트 — 별도 사용자 인증은 없다(공용 게이트)."""
    monkeypatch.setenv("ARDA_SERVICE_TOKEN", "test-token-x")
    monkeypatch.setenv("SES_FROM_EMAIL", "no-reply@test.local")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def sample_log(db: Session, admin_user: User) -> EmailLog:
    """지원자·공고·로그 최소 세팅. system 발송·applied 단계.

    **`created_by` 에 상수를 박지 않는다.** `created_by=1` 로 두면 빈 테스트 DB
    에는 id 1 인 사용자가 없어 FK 위반으로 죽는다 — 로컬에 시드가 있으면 통과하고
    CI(빈 DB)에서만 깨져서 원인을 찾기 어렵다. conftest 의 `admin_user` 를 쓴다.
    """
    posting = JobPosting(
        title="테스트 공고", description="본문", status="open", created_by=admin_user.id
    )
    db.add(posting)
    db.flush()

    application = Application(
        job_posting_id=posting.id,
        name="지원자김",
        email="candidate@test.local",
        phone="010-1234-5678",
        privacy_agreed_at=datetime.now(UTC),
    )
    db.add(application)
    db.flush()

    log = EmailLog(
        application_id=application.id,
        to_email="candidate@test.local",
        stage="applied",
        status="queued",
        actor_kind="system",
    )
    db.add(log)
    db.commit()
    return log


class TestAuth:
    def test_missing_token_401(self, client, sample_log):
        r = client.get(f"/api/v1/internal/email-logs/{sample_log.id}/render")
        assert r.status_code == 401

    def test_wrong_token_401(self, client, sample_log):
        r = client.get(
            f"/api/v1/internal/email-logs/{sample_log.id}/render",
            headers={"X-Service-Token": "wrong"},
        )
        assert r.status_code == 401

    def test_env_not_set_401(self, db: Session, monkeypatch, sample_log):
        monkeypatch.delenv("ARDA_SERVICE_TOKEN", raising=False)
        app.dependency_overrides[get_db] = lambda: db
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get(
            f"/api/v1/internal/email-logs/{sample_log.id}/render",
            headers={"X-Service-Token": "anything"},
        )
        assert r.status_code == 401
        app.dependency_overrides.pop(get_db, None)


class TestRender:
    HEADERS = {"X-Service-Token": "test-token-x"}

    def test_render_applied_template(self, client, sample_log):
        r = client.get(
            f"/api/v1/internal/email-logs/{sample_log.id}/render",
            headers=self.HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["to"] == "candidate@test.local"
        assert "지원자김" in data["body_text"]
        assert data["subject"]
        assert data["from_email"] == "no-reply@test.local"
        assert data["body_html"] is None

    def test_render_uses_committed_body(self, client, sample_log, db: Session):
        sample_log.subject = "고정된 제목"
        sample_log.body = "이 문장 그대로 나감"
        db.commit()

        r = client.get(
            f"/api/v1/internal/email-logs/{sample_log.id}/render",
            headers=self.HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "고정된 제목"
        assert data["body_text"] == "이 문장 그대로 나감"

    def test_render_missing_log_404(self, client):
        r = client.get(
            "/api/v1/internal/email-logs/999999/render",
            headers=self.HEADERS,
        )
        assert r.status_code == 404

    def test_render_already_sent_409(self, client, sample_log, db: Session):
        sample_log.status = "sent"
        db.commit()

        r = client.get(
            f"/api/v1/internal/email-logs/{sample_log.id}/render",
            headers=self.HEADERS,
        )
        assert r.status_code == 409


class TestResult:
    HEADERS = {"X-Service-Token": "test-token-x"}

    def test_record_sent(self, client, sample_log, db: Session):
        r = client.post(
            f"/api/v1/internal/email-logs/{sample_log.id}/result",
            headers=self.HEADERS,
            json={"status": "sent", "provider_message_id": "<msg-1@n8n>"},
        )
        assert r.status_code == 204, r.text

        db.refresh(sample_log)
        assert sample_log.status == "sent"
        assert sample_log.provider_message_id == "<msg-1@n8n>"
        assert sample_log.sent_at is not None

    def test_record_failed_increments_retry(self, client, sample_log, db: Session):
        sample_log.retry_count = 2
        db.commit()

        r = client.post(
            f"/api/v1/internal/email-logs/{sample_log.id}/result",
            headers=self.HEADERS,
            json={"status": "failed", "error": "smtp timeout"},
        )
        assert r.status_code == 204

        db.refresh(sample_log)
        assert sample_log.status == "failed"
        assert sample_log.retry_count == 3

    def test_record_sent_is_idempotent(self, client, sample_log, db: Session):
        client.post(
            f"/api/v1/internal/email-logs/{sample_log.id}/result",
            headers=self.HEADERS,
            json={"status": "sent", "provider_message_id": "<msg-1@n8n>"},
        )
        db.refresh(sample_log)
        first_sent_at = sample_log.sent_at
        assert sample_log.provider_message_id == "<msg-1@n8n>"

        r = client.post(
            f"/api/v1/internal/email-logs/{sample_log.id}/result",
            headers=self.HEADERS,
            json={"status": "sent", "provider_message_id": "<msg-2@n8n>"},
        )
        assert r.status_code == 204

        db.refresh(sample_log)
        assert sample_log.status == "sent"
        assert sample_log.provider_message_id == "<msg-1@n8n>"
        assert sample_log.sent_at == first_sent_at

    def test_missing_log_404(self, client):
        r = client.post(
            "/api/v1/internal/email-logs/999999/result",
            headers=self.HEADERS,
            json={"status": "sent"},
        )
        assert r.status_code == 404

    def test_missing_token_401(self, client, sample_log):
        r = client.post(
            f"/api/v1/internal/email-logs/{sample_log.id}/result",
            json={"status": "sent"},
        )
        assert r.status_code == 401


class TestPublishDispatch:
    """mail.publish 가 MAIL_DISPATCH 값에 따라 어떤 MailDispatcher 를 쓰는지.

    ADR-0035 Phase 3g · 이제 Port(MailDispatcher) 로 위임. 이 테스트는 팩토리 선택
    로직만 검증하고, 실제 SQS/n8n 호출은 어댑터 전용 테스트에서.
    """

    def test_default_uses_n8n_dispatcher(self, monkeypatch):
        # 2026-09-14: SQS 워커 폐기 후 default 를 n8n 으로 (ADR-0036).
        from app.shared import mail
        from app.adapter.outbound.mail import N8nMailDispatcher

        monkeypatch.delenv("MAIL_DISPATCH", raising=False)
        assert isinstance(mail._get_dispatcher(), N8nMailDispatcher)

    def test_worker_env_uses_sqs_dispatcher(self, monkeypatch):
        from app.shared import mail
        from app.adapter.outbound.mail import SqsMailDispatcher

        monkeypatch.setenv("MAIL_DISPATCH", "worker")
        assert isinstance(mail._get_dispatcher(), SqsMailDispatcher)

    def test_n8n_env_uses_n8n_dispatcher(self, monkeypatch):
        from app.shared import mail
        from app.adapter.outbound.mail import N8nMailDispatcher

        monkeypatch.setenv("MAIL_DISPATCH", "n8n")
        assert isinstance(mail._get_dispatcher(), N8nMailDispatcher)

    def test_publish_delegates_to_injected_dispatcher(self):
        """DI 로 mock dispatcher 를 넣으면 그것을 쓴다 — env 무시."""
        from unittest.mock import MagicMock

        from app.shared import mail
        from app.ports.output.mail_dispatcher_port import MailDispatcher

        dispatcher = MagicMock(spec=MailDispatcher)
        mail.publish(42, dispatcher=dispatcher)
        dispatcher.publish.assert_called_once_with(42)


class TestQuestions:
    """워커가 시작할 때 받는 질문 목록 — 전사를 안 기다리려면 이게 있어야 한다."""

    @pytest.fixture()
    def running(self, db: Session, admin_user: User) -> InterviewSession:
        posting = JobPosting(
            title="공고", description="본문", status="open", created_by=admin_user.id
        )
        db.add(posting)
        db.flush()
        application = Application(
            job_posting_id=posting.id,
            name="지원자김",
            email="c@test.local",
            phone="010-0000-0000",
            privacy_agreed_at=datetime.now(UTC),
        )
        db.add(application)
        db.flush()
        session = InterviewSession(
            application_id=application.id,
            token="tok-q",
            status="in_progress",
            created_by=admin_user.id,
        )
        db.add(session)
        db.flush()
        for seq, q in enumerate(["첫 질문", "둘째 질문"], start=1):
            db.add(InterviewTurn(session_id=session.id, seq=seq, question=q))
        db.flush()
        return session

    def test_번호순으로_전부_준다(self, client, running):
        r = client.get(
            "/api/v1/internal/interview/tok-q/questions",
            headers={"X-Service-Token": "test-token-x"},
        )
        assert r.status_code == 200
        assert r.json() == [
            {"seq": 1, "question": "첫 질문"},
            {"seq": 2, "question": "둘째 질문"},
        ]

    def test_토큰_없으면_401(self, client, running):
        assert client.get("/api/v1/internal/interview/tok-q/questions").status_code == 401

    def test_없는_세션이면_404(self, client):
        r = client.get(
            "/api/v1/internal/interview/nope/questions",
            headers={"X-Service-Token": "test-token-x"},
        )
        assert r.status_code == 404


class TestMarkAnswered:
    """말이 끝나는 순간 '답했다' 를 남긴다 — 워커가 부른다 (2026-09-11).

    전사는 몇 분씩 늦게 오므로 그걸 기다려 '답했다' 를 정하면, 그 사이 재접속이
    지원자를 이미 답한 질문으로 되돌린다. 되감김 자체는 test_api_interviews 가 본다.
    """

    H = {"X-Service-Token": "test-token-x"}

    @pytest.fixture()
    def running(self, db: Session, admin_user: User) -> InterviewSession:
        posting = JobPosting(
            title="공고", description="본문", status="open", created_by=admin_user.id
        )
        db.add(posting)
        db.flush()
        application = Application(
            job_posting_id=posting.id,
            name="지원자박",
            email="m@test.local",
            phone="010-0000-0000",
            privacy_agreed_at=datetime.now(UTC),
        )
        db.add(application)
        db.flush()
        session = InterviewSession(
            application_id=application.id,
            token="tok-a",
            status="in_progress",
            created_by=admin_user.id,
        )
        db.add(session)
        db.flush()
        for seq, q in enumerate(["첫 질문", "둘째 질문"], start=1):
            db.add(InterviewTurn(session_id=session.id, seq=seq, question=q))
        db.flush()
        return session

    def _turn(self, db: Session, session: InterviewSession, seq: int) -> InterviewTurn:
        return db.query(InterviewTurn).filter_by(session_id=session.id, seq=seq).one()

    def test_답했다고_남긴다(self, client, db, running):
        r = client.post("/api/v1/internal/interview/tok-a/turns/1/answered", headers=self.H)
        assert r.status_code == 200
        assert r.json()["seq"] == 1
        turn = self._turn(db, running, 1)
        assert turn.answered_at is not None
        assert turn.transcript is None          # 전사는 따로 온다

    def test_두_번_불러도_처음_시각을_지킨다(self, client, db, running):
        """재접속으로 같은 신호가 두 번 와도 '언제 답했나' 가 바뀌면 안 된다."""
        first = client.post(
            "/api/v1/internal/interview/tok-a/turns/1/answered", headers=self.H
        ).json()["answered_at"]
        second = client.post(
            "/api/v1/internal/interview/tok-a/turns/1/answered", headers=self.H
        ).json()["answered_at"]
        assert first == second

    def test_토큰_없으면_401(self, client, running):
        assert client.post("/api/v1/internal/interview/tok-a/turns/1/answered").status_code == 401

    def test_진행_중이_아니면_409(self, client, db, running):
        running.status = "done"
        db.flush()
        r = client.post("/api/v1/internal/interview/tok-a/turns/1/answered", headers=self.H)
        assert r.status_code == 409

    def test_없는_번호면_404(self, client, running):
        r = client.post("/api/v1/internal/interview/tok-a/turns/9/answered", headers=self.H)
        assert r.status_code == 404


class TestAttachAnswerAudio:
    """전사에 실패한 답변의 **음성이 어디 있는지**를 남긴다 (2026-09-16).

    실시간 면접은 음성을 저장하지 않는다. 그런데 전사가 실패하면 그 답변은
    `[전사 지연 · …]` 자리표시자로만 남아 지원자가 한 말을 되살릴 길이 없다
    (2026-09-15 세션 75, ADR-0038). 받아쓰지 못한 답변에 한해 워커가 음성을
    올리고 그 키를 여기에 남긴다 — 담당자가 「다시 받아쓰기」를 누르면 쓰인다.
    """

    H = {"X-Service-Token": "test-token-x"}
    KEY = "interviews/11111111-2222-3333-4444-555555555555/answer.wav"

    @pytest.fixture()
    def running(self, db: Session, admin_user: User) -> InterviewSession:
        posting = JobPosting(
            title="공고", description="본문", status="open", created_by=admin_user.id
        )
        db.add(posting)
        db.flush()
        application = Application(
            job_posting_id=posting.id,
            name="지원자최",
            email="audio@test.local",
            phone="010-0000-0000",
            privacy_agreed_at=datetime.now(UTC),
        )
        db.add(application)
        db.flush()
        session = InterviewSession(
            application_id=application.id,
            token="tok-audio",
            status="in_progress",
            created_by=admin_user.id,
        )
        db.add(session)
        db.flush()
        db.add(InterviewTurn(session_id=session.id, seq=1, question="첫 질문"))
        db.add(
            InterviewTurn(
                session_id=session.id, seq=2, question="둘째 질문",
                transcript="제대로 받아쓴 답변입니다",
            )
        )
        db.flush()
        return session

    def _turn(self, db: Session, session: InterviewSession, seq: int) -> InterviewTurn:
        return db.query(InterviewTurn).filter_by(session_id=session.id, seq=seq).one()

    def test_아직_글이_없는_회차에_음성을_붙인다(self, client, db, running):
        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/1/audio",
            headers=self.H, json={"audio_s3_key": self.KEY},
        )
        assert r.status_code == 200
        assert self._turn(db, running, 1).audio_s3_key == self.KEY

    def test_자리표시자_회차에도_붙인다(self, client, db, running):
        turn = self._turn(db, running, 1)
        turn.transcript = "[전사 지연 · 발화 43.9초]"
        db.flush()

        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/1/audio",
            headers=self.H, json={"audio_s3_key": self.KEY},
        )
        assert r.status_code == 200

    def test_이미_받아쓴_답변에는_안_붙인다(self, client, db, running):
        """붙이면 담당자가 멀쩡한 답변을 다시 받아쓰게 된다."""
        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/2/audio",
            headers=self.H, json={"audio_s3_key": self.KEY},
        )
        assert r.status_code == 409
        assert self._turn(db, running, 2).audio_s3_key is None

    def test_남의_파일_키는_거절한다(self, client, db, running):
        """키를 그냥 믿으면 남의 이력서를 답변이라고 넘겨 읽게 할 수 있다."""
        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/1/audio",
            headers=self.H,
            json={"audio_s3_key": "applications/9999/resume.pdf"},
        )
        assert r.status_code == 422
        assert self._turn(db, running, 1).audio_s3_key is None

    def test_없는_회차는_404(self, client, running):
        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/9/audio",
            headers=self.H, json={"audio_s3_key": self.KEY},
        )
        assert r.status_code == 404

    def test_서비스_토큰이_없으면_거절한다(self, client, running):
        r = client.post(
            "/api/v1/internal/interview/tok-audio/turns/1/audio",
            json={"audio_s3_key": self.KEY},
        )
        assert r.status_code in (401, 403)
