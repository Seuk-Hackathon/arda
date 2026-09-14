"""회사 통합 API 테스트 (ADR-0037).

- Bearer 인증 (누락·잘못됨·유효)
- 지원자 생성 성공
- Idempotency: 같은 external_id 로 두 번 오면 최초 결과 반환
- 유효성 검사: 이메일 형식·birth_date·공고 없음
"""
from __future__ import annotations

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models import Application, CompanyProfile, IntegrationClient, JobPosting, User


@pytest.fixture()
def client(db: Session, monkeypatch) -> TestClient:
    monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://test.local")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def company(db: Session) -> CompanyProfile:
    # company_profile 은 id=1 singleton (ck_company_profile_singleton). 이미 있으면 재사용.
    row = db.get(CompanyProfile, 1)
    if row is None:
        row = CompanyProfile(id=1, name="테스트회사")
        db.add(row)
        db.commit()
    return row


@pytest.fixture()
def posting(db: Session, admin_user: User) -> JobPosting:
    row = JobPosting(
        title="테스트 공고",
        description="본문",
        status="open",
        created_by=admin_user.id,
        public_token="posting-token-abc",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def integration_client(
    db: Session, company: CompanyProfile
) -> tuple[IntegrationClient, str]:
    """활성 통합 클라이언트 + 원본 API key 반환."""
    raw_key = "arda_ak_" + "x" * 32
    hashed = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    row = IntegrationClient(
        company_id=company.id,
        api_key_hash=hashed,
        api_key_prefix=raw_key[:24],
        name="테스트 통합",
    )
    db.add(row)
    db.commit()
    return row, raw_key


class TestAuth:
    def test_missing_header_401(self, client, posting):
        r = client.post(
            "/api/v1/integrations/applications",
            json=_valid_payload(posting.public_token),
        )
        assert r.status_code == 401

    def test_wrong_key_401(self, client, posting, integration_client):
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": "Bearer arda_ak_wrong"},
            json=_valid_payload(posting.public_token),
        )
        assert r.status_code == 401

    def test_valid_key_201(self, client, posting, integration_client):
        _, raw = integration_client
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=_valid_payload(posting.public_token),
        )
        assert r.status_code == 201, r.text


class TestCreate:
    def test_creates_application(self, client, db, posting, integration_client):
        _, raw = integration_client
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=_valid_payload(posting.public_token, external_id="ext-1"),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "received"
        assert body["arda_application_id"] > 0

        row = db.get(Application, body["arda_application_id"])
        assert row is not None
        assert row.external_id == "ext-1"
        assert row.source == "integration"
        assert row.name == "홍길동"

    def test_missing_posting_404(self, client, posting, integration_client):
        _, raw = integration_client
        payload = _valid_payload("non-existent-token")
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=payload,
        )
        assert r.status_code == 404

    def test_invalid_email_422(self, client, posting, integration_client):
        _, raw = integration_client
        payload = _valid_payload(posting.public_token)
        payload["applicant"]["email"] = "not-an-email"
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=payload,
        )
        assert r.status_code == 422

    def test_invalid_birth_date_422(self, client, posting, integration_client):
        _, raw = integration_client
        payload = _valid_payload(posting.public_token)
        payload["applicant"]["birth_date"] = "abcd1234"
        r = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=payload,
        )
        assert r.status_code == 422


class TestIdempotency:
    def test_same_external_id_returns_original(
        self, client, db, posting, integration_client
    ):
        _, raw = integration_client
        payload = _valid_payload(posting.public_token, external_id="ext-dup")

        r1 = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=payload,
        )
        assert r1.status_code == 201
        first_id = r1.json()["arda_application_id"]

        # 같은 external_id · 다른 이름으로 재시도 → 최초 지원자 그대로 반환
        payload["applicant"]["name"] = "다른이름"
        r2 = client.post(
            "/api/v1/integrations/applications",
            headers={"Authorization": f"Bearer {raw}"},
            json=payload,
        )
        assert r2.status_code == 201
        body = r2.json()
        assert body["arda_application_id"] == first_id
        assert body["status"] == "duplicate"

        # DB 에는 여전히 한 행만 · 이름도 최초 그대로
        row = db.get(Application, first_id)
        assert row is not None
        assert row.name == "홍길동"


def _valid_payload(
    posting_token: str, external_id: str = "ext-abc-123"
) -> dict:
    return {
        "external_id": external_id,
        "posting_token": posting_token,
        "applicant": {
            "name": "홍길동",
            "email": "hong@example.com",
            "phone": "010-1234-5678",
            "birth_date": "19980315",
        },
        "cover_letter": "저는 백엔드 개발자입니다.",
        "source": "integration",
    }
