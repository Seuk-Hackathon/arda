"""지원자 앱 로그인 (ADR-0033) — 이메일 + 생년월일 8자리.

**틀렸을 때 남의 지원서가 열린다.** 그래서 규칙 하나에 테스트 하나를 붙인다.
특히 아래 넷은 무너져도 화면상 아무 일이 없어 보여서 제일 위험하다.

- **지원자 토큰이 직원 경로를 못 탄다.** 같은 키로 서명하므로 서명 검증은
  이걸 막지 못한다 — 토큰 종류(`typ`)만이 구분선이다
- **직원 토큰도 지원자 경로를 못 탄다.** 반대 방향도 막혀야 한다
- **없는 이메일과 틀린 생년월일이 같은 응답이다.** 다르면 "이 사람이 여기
  지원했는가"를 확인하는 도구가 된다
- **생년월일이 없는 옛 지원서는 로그인이 안 된다.** 빈 값끼리 맞아떨어지면 안 된다

나머지(잠금·여러 지원·단계 문구)는 흐름이 도는지를 본다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.talent.api import applicant_auth
from app.db import get_db
from app.main import app
from app.models import Application, User
from app.security import create_access_token, create_applicant_token

LOGIN = "/api/v1/public/applicant/login"
ME = "/api/v1/applicant/me"


@pytest.fixture()
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clear_lock():
    """실패 횟수는 프로세스 메모리에 산다 — 테스트끼리 새게 두지 않는다."""
    applicant_auth._FAILS.clear()
    yield
    applicant_auth._FAILS.clear()


def _applicant(db: Session, application: Application, **kw) -> Application:
    """기존 지원서에 생년월일을 붙인다."""
    application.birth_date = kw.pop("birth_date", date(1998, 4, 12))
    for k, v in kw.items():
        setattr(application, k, v)
    db.flush()
    return application


class TestLogin:
    def test_이메일과_생년월일이_맞으면_토큰이_나온다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        res = client.post(LOGIN, json={"email": a.email, "birth_date": "19980412"})

        assert res.status_code == 200
        body = res.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    def test_대소문자와_공백은_무시한다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application, email="Kwak@Example.com")
        # 지원 폼과 앱에서 같은 사람이 다르게 칠 수 있다
        a.email = "kwak@example.com"
        db.flush()
        res = client.post(LOGIN, json={"email": "  KWAK@Example.COM ", "birth_date": "19980412"})
        assert res.status_code == 200

    def test_틀린_생년월일과_없는_이메일이_같은_응답이다(
        self, client, db: Session, application: Application
    ):
        """**이게 갈리면 지원 사실 자체가 새어 나간다.**"""
        a = _applicant(db, application)
        wrong_birth = client.post(LOGIN, json={"email": a.email, "birth_date": "19990101"})
        no_such = client.post(LOGIN, json={"email": "nobody@example.com", "birth_date": "19980412"})

        assert wrong_birth.status_code == no_such.status_code == 401
        # `request_id` 는 요청마다 다른 값이라 비교에서 뺀다 — 유출이 아니다.
        strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
        assert strip(wrong_birth) == strip(no_such)

    def test_형식이_틀려도_422가_아니라_401이다(
        self, client, db: Session, application: Application
    ):
        """422 는 '형식은 맞다'는 신호가 되어 떠보는 데 쓰인다."""
        _applicant(db, application)
        res = client.post(LOGIN, json={"email": application.email, "birth_date": "98/04/12"})
        assert res.status_code == 401

    def test_생년월일이_없는_옛_지원서는_못_들어온다(
        self, client, db: Session, application: Application
    ):
        application.birth_date = None
        db.flush()
        res = client.post(LOGIN, json={"email": application.email, "birth_date": "19980412"})
        assert res.status_code == 401

    def test_다섯_번_틀리면_잠긴다(self, client, db: Session, application: Application):
        a = _applicant(db, application)
        for _ in range(applicant_auth.MAX_ATTEMPTS):
            assert client.post(LOGIN, json={"email": a.email, "birth_date": "19000101"}).status_code == 401

        # 잠긴 뒤에는 **맞는 값을 넣어도** 막힌다 — 그래야 시도 상한이 의미가 있다
        res = client.post(LOGIN, json={"email": a.email, "birth_date": "19980412"})
        assert res.status_code == 429

    def test_성공하면_실패_횟수가_지워진다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        client.post(LOGIN, json={"email": a.email, "birth_date": "19000101"})
        assert client.post(LOGIN, json={"email": a.email, "birth_date": "19980412"}).status_code == 200
        assert a.email not in applicant_auth._FAILS


class TestTokenBoundary:
    """**같은 비밀키로 서명한다.** 토큰 종류만이 두 세계를 가른다."""

    def test_지원자_토큰으로_직원_경로를_못_탄다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        _applicant(db, application)
        token = create_applicant_token(application.email)
        res = client.get("/api/v1/applications", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    def test_sub_가_숫자여도_직원이_되지_않는다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """예전 `get_current_user` 는 sub 로 User 를 찾기만 했다 — 지원자 토큰의
        sub 가 어떤 User 의 id 와 같기만 해도 그 사람이 됐다."""
        token = create_applicant_token(str(admin_user.id))
        res = client.get("/api/v1/applications", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    def test_직원_토큰으로_지원자_경로를_못_탄다(
        self, client, db: Session, admin_user: User
    ):
        token = create_access_token(admin_user.id, admin_user.role)
        res = client.get(ME, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


class TestMe:
    def test_내_지원만_보인다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        token = create_applicant_token(a.email)
        res = client.get(ME, headers={"Authorization": f"Bearer {token}"})

        assert res.status_code == 200
        body = res.json()
        assert body["email"] == a.email
        assert [x["id"] for x in body["applications"]] == [a.id]

    def test_평가나_담당자_정보가_없다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        # **필드가 늘면 여기서 걸린다.** 그게 이 테스트의 목적이다 —
        # 지원자에게 나가는 것이 조용히 늘어나는 일이 없게.
        allowed = {
            "id", "posting_title", "stage_label", "applied_at",
            "interviews", "aptitudes", "schedules",
        }
        assert set(body["applications"][0]) == allowed
        assert "ai_summary" not in body

    def test_불합격을_앱이_먼저_말하지_않는다(
        self, client, db: Session, application: Application
    ):
        """담당자가 통보하기 전에 화면이 앞질러 말하면 안 된다 (portal 과 같은 규칙)."""
        a = _applicant(db, application)
        a.current_stage = "rejected"
        db.flush()
        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        label = body["applications"][0]["stage_label"]
        assert label == "전형 종료"
        assert "불합격" not in label

    def test_토큰이_없으면_401(self, client):
        assert client.get(ME).status_code == 401

    def test_만료된_토큰은_거부한다(self, client, db: Session, application: Application):
        import jwt

        from app.security import JWT_ALGORITHM, JWT_SECRET, TYP_APPLICANT

        expired = jwt.encode(
            {
                "sub": application.email,
                "typ": TYP_APPLICANT,
                "exp": datetime.now(UTC) - timedelta(minutes=1),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        res = client.get(ME, headers={"Authorization": f"Bearer {expired}"})
        assert res.status_code == 401


class TestMyInterviews:
    """면접 입장 경로 (ADR-0033 후속).

    **지원자가 로그인해 놓고도 면접에 못 들어가는 것**이 원래 구멍이었다 —
    메일함에서 링크를 찾는 것이 유일한 길이었다. 그래서 자기 면접의 토큰을
    같이 내린다. 본인 토큰으로 조회한 자기 면접이라 새로 여는 비밀이 아니다.
    """

    def _session(self, db: Session, application: Application, admin_user: User, status: str):
        from app.models import InterviewSession

        row = InterviewSession(
            application_id=application.id,
            token=f"tok-{status}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def test_들어갈_수_있는_면접의_토큰이_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        a = _applicant(db, application)
        s = self._session(db, a, admin_user, "pending")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        ivs = body["applications"][0]["interviews"]
        assert [x["token"] for x in ivs] == [s.token]
        assert ivs[0]["status"] == "pending"

    def test_끝난_면접도_온다_만료된_것만_뺀다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """2026-09-09 개정.

        끝난 것을 빼면 면접을 마친 지원자의 화면에서 면접이 **통째로 사라진다** —
        "완료"와 "아직 안 잡힘"이 같은 화면이 되어, 방금 면접을 본 사람이 자기가
        낸 것이 접수됐는지 알 수 없다(앱 실측).

        `expired` 는 계속 뺀다. 그건 **지원자가 놓친 것**이라 띄워도 할 수 있는
        일이 없다. 화면은 `status` 를 보고 끝난 줄에 문을 안 그린다.
        """
        a = _applicant(db, application)
        done = self._session(db, a, admin_user, "done")
        self._session(db, a, admin_user, "expired")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        rows = body["applications"][0]["interviews"]
        assert [x["token"] for x in rows] == [done.token]
        assert rows[0]["status"] == "done"

    def test_남의_면접은_안_온다(
        self, client, db: Session, application: Application, admin_user: User, posting
    ):
        """**이게 무너지면 남의 면접방에 들어갈 수 있다.**"""
        a = _applicant(db, application)
        other = Application(
            job_posting_id=posting.id,
            name="남",
            email="someone-else@fixture.local",
            phone="010-0000-0000",
            privacy_agreed_at=datetime.now(UTC),
            birth_date=date(1990, 1, 1),
        )
        db.add(other)
        db.flush()
        self._session(db, other, admin_user, "in_progress")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        tokens = [x["token"] for app in body["applications"] for x in app["interviews"]]
        assert tokens == []


class TestMyOtherTokens:
    """인적성·일정도 같이 내린다 (2026-09-08, 앱 요청).

    **로그인이 유일한 문이면 이것들이 여기 없을 때 갈 길이 없다.** 앱에는
    메일함이 없어서, 빠뜨리면 ADR-0033 이 없애려던 "앱인데 메일을 거쳐야 한다"가
    그 두 탭에 그대로 남는다. 면접 토큰과 같은 근거다.
    """

    def _aptitude(self, db: Session, application: Application, admin_user: User, status: str):
        from app.models import AptitudeSession

        row = AptitudeSession(
            application_id=application.id,
            token=f"apt-{status}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def _schedule(self, db: Session, application: Application, admin_user: User, status: str):
        from app.models import ScheduleProposal

        row = ScheduleProposal(
            application_id=application.id,
            token=f"sch-{status}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def test_인적성은_낸_것도_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """면접과 같은 이유다 — 낸 것을 빼면 "제출했습니다" 를 말할 수 없다."""
        a = _applicant(db, application)
        pending = self._aptitude(db, a, admin_user, "pending")
        done = self._aptitude(db, a, admin_user, "done")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        rows = body["applications"][0]["aptitudes"]
        assert [x["token"] for x in rows] == [pending.token, done.token]

    def test_일정은_확정된_것도_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """확정 뒤에도 **언제로 잡혔는지 다시 볼 일**이 있다 — 면접·인적성과 다르다."""
        a = _applicant(db, application)
        proposed = self._schedule(db, a, admin_user, "proposed")
        confirmed = self._schedule(db, a, admin_user, "confirmed")
        self._schedule(db, a, admin_user, "expired")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        got = {x["token"] for x in body["applications"][0]["schedules"]}
        assert got == {proposed.token, confirmed.token}

    def test_남의_것은_안_온다(
        self, client, db: Session, application: Application, posting, admin_user: User
    ):
        """**이게 무너지면 남의 인적성·일정 링크가 열린다.**"""
        a = _applicant(db, application)
        other = Application(
            job_posting_id=posting.id,
            name="남",
            email="other-tokens@fixture.local",
            phone="010-0000-0000",
            privacy_agreed_at=datetime.now(UTC),
            birth_date=date(1990, 1, 1),
        )
        db.add(other)
        db.flush()
        self._aptitude(db, other, admin_user, "pending")
        self._schedule(db, other, admin_user, "proposed")

        token = create_applicant_token(a.email)
        body = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

        for app_row in body["applications"]:
            assert app_row["aptitudes"] == []
            assert app_row["schedules"] == []


class TestExpiryNotYetStamped:
    """**아직 `expired` 로 찍히지 않은 만료** (2026-09-15 앱 실기기, 민아님 보고).

    만료 판정은 토큰을 열 때만 돈다(스케줄러 없음). 아무도 안 열었으면 기한이
    지나도 DB 는 `pending` 이라, 상태만 보고 거르던 이 목록을 그대로 통과했다.
    앱 홈은 「3일 남음」이라 적고, 눌러 들어가면 「기한이 지났습니다」가 떴다.

    **끝난 것은 기한과 무관하게 남긴다** — 그걸 같이 거르면 09-09 에 고쳤던
    "마친 면접이 화면에서 사라지는" 문제가 되돌아온다.
    """

    def _iv(self, db: Session, application: Application, admin_user: User,
            status: str, days: int):
        from app.models import InterviewSession

        row = InterviewSession(
            application_id=application.id,
            token=f"iv-{status}-{days}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=days),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def _apt(self, db: Session, application: Application, admin_user: User,
             status: str, days: int):
        from app.models import AptitudeSession

        row = AptitudeSession(
            application_id=application.id,
            token=f"apt-{status}-{days}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=days),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def _sch(self, db: Session, application: Application, admin_user: User,
             status: str, days: int):
        from app.models import ScheduleProposal

        row = ScheduleProposal(
            application_id=application.id,
            token=f"sch-{status}-{days}-{application.id}",
            status=status,
            expires_at=datetime.now(UTC) + timedelta(days=days),
            created_by=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    def _me(self, client, a: Application) -> dict:
        token = create_applicant_token(a.email)
        return client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()

    def test_기한_지난_pending_면접은_안_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        a = _applicant(db, application)
        alive = self._iv(db, a, admin_user, "pending", days=3)
        self._iv(db, a, admin_user, "pending", days=-1)  # 아무도 안 열어 아직 pending

        rows = self._me(client, a)["applications"][0]["interviews"]
        assert [x["token"] for x in rows] == [alive.token]

    def test_기한이_지나도_끝난_면접은_남는다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """지원자가 놓친 것이 아니라 **다시 볼 자리**다."""
        a = _applicant(db, application)
        done = self._iv(db, a, admin_user, "done", days=-30)

        rows = self._me(client, a)["applications"][0]["interviews"]
        assert [x["token"] for x in rows] == [done.token]

    def test_기한_지난_pending_인적성은_안_오고_낸_것은_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        a = _applicant(db, application)
        self._apt(db, a, admin_user, "pending", days=-1)
        submitted = self._apt(db, a, admin_user, "done", days=-1)

        rows = self._me(client, a)["applications"][0]["aptitudes"]
        assert [x["token"] for x in rows] == [submitted.token]

    def test_기한_지난_제안은_안_오고_확정은_온다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """확정된 일정은 **언제로 잡혔는지 다시 볼 일**이 있다."""
        a = _applicant(db, application)
        self._sch(db, a, admin_user, "proposed", days=-2)
        confirmed = self._sch(db, a, admin_user, "confirmed", days=-2)

        rows = self._me(client, a)["applications"][0]["schedules"]
        assert [x["token"] for x in rows] == [confirmed.token]

    def test_목록을_봐도_상태를_바꾸지_않는다(
        self, client, db: Session, application: Application, admin_user: User
    ):
        """GET 은 쓰기를 하지 않는다 — 지원자가 앱을 켤 때마다 커밋이 생기면 안 된다."""
        a = _applicant(db, application)
        row = self._iv(db, a, admin_user, "pending", days=-1)
        db.commit()

        self._me(client, a)

        db.expire_all()
        assert row.status == "pending", "목록 조회가 만료를 찍었다"


class TestPasswordLogin:
    """지원자 비밀번호 로그인 (2026-09-16, ADR-0033 개정).

    생년월일은 **경우의 수가 만 단위**고 **새어도 못 바꾸는 값**이다. 게다가 지원
    폼에서 선택이라 그 칸을 비운 사람은 영영 못 들어왔다. 접수 메일로 받은 링크에서
    한 번 정하면 그 뒤로는 이메일 + 비밀번호로 들어온다.
    """

    SETUP = "/api/v1/public/applicant/password-setup-request"
    LOGIN = "/api/v1/public/applicant/login"

    def _issue(self, db: Session, email: str) -> str:
        from app.talent import applicant_password

        raw = applicant_password.issue_token(db, email)
        db.commit()
        return raw

    def test_링크를_받아_비밀번호를_정하고_들어온다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        token = self._issue(db, a.email)

        opened = client.get(f"/api/v1/public/applicant/set-password/{token}")
        assert opened.status_code == 200
        assert opened.json()["email"] == a.email

        done = client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "짧지않은비밀번호1"},
        )
        assert done.status_code == 200

        r = client.post(
            self.LOGIN, json={"email": a.email, "password": "짧지않은비밀번호1"}
        )
        assert r.status_code == 200
        assert r.json()["access_token"]

    def test_한_번_쓴_링크는_죽는다(
        self, client, db: Session, application: Application
    ):
        a = _applicant(db, application)
        token = self._issue(db, a.email)
        client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "비밀번호12345"},
        )

        again = client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "다른비밀번호12345"},
        )
        assert again.status_code == 410
        assert client.get(f"/api/v1/public/applicant/set-password/{token}").status_code == 410

    def test_새로_발급하면_이전_링크가_죽는다(
        self, client, db: Session, application: Application
    ):
        """오래된 메일에서 누른 링크가 먹으면 안 된다."""
        a = _applicant(db, application)
        old = self._issue(db, a.email)
        self._issue(db, a.email)

        assert client.get(f"/api/v1/public/applicant/set-password/{old}").status_code == 410

    def test_기한이_지난_링크는_안_먹는다(
        self, client, db: Session, application: Application
    ):
        from app.models import ApplicantPasswordToken

        a = _applicant(db, application)
        token = self._issue(db, a.email)
        row = db.scalars(select(ApplicantPasswordToken)).first()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        assert client.get(f"/api/v1/public/applicant/set-password/{token}").status_code == 410

    def test_비밀번호를_정하면_생년월일로는_못_들어온다(
        self, client, db: Session, application: Application
    ):
        """둘 다 열어 두면 약한 쪽으로 들어온다 — 생년월일은 SNS·이력서로 알 수 있다."""
        a = _applicant(db, application)
        before = client.post(
            self.LOGIN, json={"email": a.email, "birth_date": "19980412"}
        )
        assert before.status_code == 200, "설정 전에는 생년월일로 들어온다"

        token = self._issue(db, a.email)
        client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "비밀번호12345"},
        )

        after = client.post(
            self.LOGIN, json={"email": a.email, "birth_date": "19980412"}
        )
        assert after.status_code == 401

    def test_틀린_비밀번호는_401(self, client, db: Session, application: Application):
        a = _applicant(db, application)
        token = self._issue(db, a.email)
        client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "비밀번호12345"},
        )

        r = client.post(self.LOGIN, json={"email": a.email, "password": "틀린비밀번호"})
        assert r.status_code == 401
        assert "생년월일" not in r.text, "어느 쪽이 틀렸는지 알려주면 안 된다"

    def test_bcrypt_가_자르는_길이는_거절한다(
        self, client, db: Session, application: Application
    ):
        """한글 25자면 75바이트다. 자르면 뒤를 무엇으로 치든 같은 비밀번호가 된다."""
        a = _applicant(db, application)
        token = self._issue(db, a.email)

        r = client.post(
            f"/api/v1/public/applicant/set-password/{token}",
            json={"password": "가" * 25},
        )
        assert r.status_code == 422

    def test_없는_이메일로_요청해도_202(self, client, db: Session):
        """있고 없고를 다르게 답하면 "이 사람이 여기 지원했나" 를 떠볼 수 있다."""
        r = client.post(self.SETUP, json={"email": "nobody@test.local"})
        assert r.status_code == 202

    def test_지원_이력이_있으면_링크를_만든다(
        self, client, db: Session, application: Application
    ):
        from app.models import ApplicantPasswordToken

        a = _applicant(db, application)
        with patch("app.talent.api.applicant_auth._send_password_mail") as sent:
            r = client.post(self.SETUP, json={"email": a.email})
        sent.assert_called_once()

        assert r.status_code == 202
        rows = db.scalars(
            select(ApplicantPasswordToken).where(ApplicantPasswordToken.email == a.email)
        ).all()
        assert len(rows) == 1
        assert rows[0].token_hash != ""
