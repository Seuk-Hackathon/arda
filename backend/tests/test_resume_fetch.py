"""회사 통합 API 이력서 받기 (ADR-0037 Phase B · 2026-09-17).

네트워크는 타지 않는다 — `resume_fetch.open_url` 과 이름 풀이를 바꿔 끼운다.
보는 것은 세 갈래다.

1. **열지 않을 주소를 안 여는가** — 메타데이터·사설·루프백·다른 포트·리다이렉트 우회
2. **받은 것을 지원 폼과 같은 규격으로 거르는가** — 크기·형식(바이트 판정)
3. **통합 API 에서 결과가 맞게 이어지는가** — 받으면 `files` 행 + 요약, 못 받으면
   안내 메일만(요약 없음), 회사가 다시 보내면 다시 받기
"""
from __future__ import annotations

import base64
import io
import socket
import zipfile

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application import resume_fetch as rf
from app.application.resume_fetch import FetchError
from app.db import get_db
from app.main import app
from app.models import (
    Application,
    CompanyProfile,
    EmailLog,
    File,
    IntegrationClient,
    JobPosting,
    StageHistory,
    User,
)

PDF = b"%PDF-1.7\n" + b"x" * 200


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


DOCX = _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"})
HWPX = _zip({"mimetype": b"application/hwp+zip", "Contents/section0.xml": b"<h/>"})
HWP = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 500 + b"HWP Document File" + b"\0" * 50
DOC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 500 + b"Microsoft Word" + b"\0" * 50


# ── 형식 판정 ────────────────────────────────────────────────────────
class TestSniff:
    @pytest.mark.parametrize(
        ("data", "ext"),
        [(PDF, "pdf"), (DOCX, "docx"), (HWPX, "hwpx"), (HWP, "hwp")],
    )
    def test_허용_형식(self, data, ext):
        assert rf.sniff(data) == ext

    @pytest.mark.parametrize(
        "data",
        [
            "<html><body>로그인이 필요합니다</body></html>".encode(),  # 만료 링크가 흔히 주는 것
            DOC,  # 같은 OLE 껍데기지만 hwp 가 아니다
            _zip({"xl/workbook.xml": b"<x/>"}),  # 엑셀
            b"PK\x03\x04broken",
            b"",
        ],
    )
    def test_그_밖은_거절(self, data):
        assert rf.sniff(data) is None

    def test_확장자가_내용과_다르면_파일명을_안_쓴다(self):
        assert rf.safe_filename("이력서.pdf", "hwp") == "resume.hwp"
        assert rf.safe_filename("홍길동_이력서.PDF", "pdf") == "홍길동_이력서.PDF"
        assert rf.safe_filename("../../etc/passwd.pdf", "pdf") == "passwd.pdf"
        assert rf.safe_filename(None, "docx") == "resume.docx"


# ── 주소 확인 ────────────────────────────────────────────────────────
def _fake_dns(monkeypatch, table: dict[str, list[str]]):
    import ipaddress

    def getaddrinfo(host, port, type=0):  # noqa: A002
        addrs = table.get(host)
        if addrs is None:
            try:  # IP 리터럴은 실제 getaddrinfo 처럼 그대로 돌려준다
                addrs = [str(ipaddress.ip_address(host))]
            except ValueError:
                raise socket.gaierror("no such host") from None
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, type, 6, "", (a, port))
            for a in addrs
        ]

    monkeypatch.setattr(rf.socket, "getaddrinfo", getaddrinfo)


class TestResolve:
    @pytest.mark.parametrize(
        "addr",
        [
            "169.254.169.254",  # EC2 메타데이터 — 가장 먼저 노려지는 곳
            "127.0.0.1",
            "10.0.0.5",
            "172.31.0.10",  # VPC 기본 대역
            "192.168.0.1",
            "100.64.0.1",  # CGNAT
            "0.0.0.0",
            "::1",
            "::ffff:127.0.0.1",  # IPv6 에 싼 루프백
            "fd00::1",
        ],
    )
    def test_내부_주소는_거절(self, monkeypatch, addr):
        _fake_dns(monkeypatch, {"files.example.com": [addr]})
        with pytest.raises(FetchError) as e:
            rf.resolve_public("files.example.com", 443)
        assert e.value.reason == "blocked_host"

    def test_하나라도_내부면_거절(self, monkeypatch):
        _fake_dns(monkeypatch, {"files.example.com": ["93.184.216.34", "10.0.0.5"]})
        with pytest.raises(FetchError) as e:
            rf.resolve_public("files.example.com", 443)
        assert e.value.reason == "blocked_host"

    def test_공인_주소는_통과_IPv4_우선(self, monkeypatch):
        _fake_dns(monkeypatch, {"files.example.com": ["2606:2800:220:1::1", "93.184.216.34"]})
        assert rf.resolve_public("files.example.com", 443) == "93.184.216.34"

    def test_이름이_안_풀리면(self, monkeypatch):
        _fake_dns(monkeypatch, {})
        with pytest.raises(FetchError) as e:
            rf.resolve_public("nope.example.com", 443)
        assert e.value.reason == "dns"


# ── 내려받기 ─────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self._body = body
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, amt=None):
        return self._body if amt is None else self._body[:amt]


class _Conn:
    def close(self):
        pass


@pytest.fixture()
def web(monkeypatch):
    """가짜 인터넷. `routes[(host, target)] = _Resp(...)`. 연 주소를 `opened` 에 남긴다."""
    _fake_dns(
        monkeypatch,
        {
            "files.example.com": ["93.184.216.34"],
            "cdn.example.com": ["93.184.216.35"],
            "metadata.evil.com": ["169.254.169.254"],
        },
    )
    routes: dict[tuple[str, str], _Resp] = {}
    opened: list[tuple[str, str, int, str, str]] = []

    def open_url(scheme, host, port, ip, target):
        opened.append((scheme, host, port, ip, target))
        resp = routes.get((host, target))
        if resp is None:
            raise ConnectionRefusedError()
        return _Conn(), resp

    monkeypatch.setattr(rf, "open_url", open_url)
    return routes, opened


class TestDownload:
    def test_PDF_를_받는다(self, web):
        routes, opened = web
        routes[("files.example.com", "/cv/%ED%99%8D.pdf?sig=abc")] = _Resp(body=PDF)
        got = rf.download("https://files.example.com/cv/%ED%99%8D.pdf?sig=abc")
        assert (got.ext, got.filename, got.data) == ("pdf", "홍.pdf", PDF)
        # 확인한 IP 로 붙었다 — 이름을 다시 풀지 않는다
        assert opened == [("https", "files.example.com", 443, "93.184.216.34",
                           "/cv/%ED%99%8D.pdf?sig=abc")]

    def test_리다이렉트로_메타데이터에_보내면_거기서_멈춘다(self, web):
        routes, opened = web
        routes[("files.example.com", "/cv.pdf")] = _Resp(
            302, headers={"Location": "http://metadata.evil.com/latest/meta-data/"}
        )
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/cv.pdf")
        assert e.value.reason == "blocked_host"
        assert len(opened) == 1, "내부 주소로는 한 번도 붙지 않아야 한다"

    def test_IP_리터럴로_직접도_못_간다(self, web):
        _, opened = web
        with pytest.raises(FetchError) as e:
            rf.download("http://169.254.169.254/latest/meta-data/")
        assert e.value.reason == "blocked_host"
        assert opened == []

    def test_공인_리다이렉트는_따라간다(self, web):
        routes, _ = web
        routes[("files.example.com", "/cv")] = _Resp(301, headers={"Location": "https://cdn.example.com/x/cv.docx"})
        routes[("cdn.example.com", "/x/cv.docx")] = _Resp(body=DOCX)
        got = rf.download("https://files.example.com/cv")
        assert (got.ext, got.filename) == ("docx", "cv.docx")

    def test_리다이렉트는_세_번까지(self, web):
        routes, _ = web
        for i in range(5):
            routes[("files.example.com", f"/r{i}")] = _Resp(302, headers={"Location": f"/r{i + 1}"})
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/r0")
        assert e.value.reason == "too_many_redirects"

    @pytest.mark.parametrize(
        ("url", "reason"),
        [
            ("ftp://files.example.com/cv.pdf", "bad_url"),
            ("file:///etc/passwd", "bad_url"),
            ("https://files.example.com:8443/cv.pdf", "blocked_host"),
            ("http://files.example.com:6379/", "blocked_host"),
            ("https://files.example.com@metadata.evil.com/cv.pdf", "bad_url"),
            ("https://files.example.com:99999/cv.pdf", "bad_url"),
            ("https://files.example.com/" + "a" * 2100, "bad_url"),
        ],
    )
    def test_주소_모양으로_거절(self, web, url, reason):
        _, opened = web
        with pytest.raises(FetchError) as e:
            rf.download(url)
        assert e.value.reason == reason
        assert opened == []

    def test_크기_신고가_크면_읽지_않는다(self, web):
        routes, _ = web
        routes[("files.example.com", "/big.pdf")] = _Resp(
            body=PDF, headers={"Content-Length": str(rf.MAX_BYTES + 1)}
        )
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/big.pdf")
        assert e.value.reason == "too_large"

    def test_크기_신고가_거짓이어도_읽으며_끊는다(self, web, monkeypatch):
        routes, _ = web
        monkeypatch.setattr(rf, "MAX_BYTES", 100)
        routes[("files.example.com", "/big.pdf")] = _Resp(
            body=PDF, headers={"Content-Length": "10"}
        )
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/big.pdf")
        assert e.value.reason == "too_large"

    @pytest.mark.parametrize(
        ("resp", "reason"),
        [
            (_Resp(body=b"<html>expired</html>", headers={"Content-Type": "application/pdf"}), "bad_type"),
            (_Resp(403), "http_status"),
            (_Resp(302), "http_status"),  # Location 없는 리다이렉트
            (_Resp(body=b""), "empty"),
        ],
    )
    def test_받은_것이_이력서가_아니면(self, web, resp, reason):
        routes, _ = web
        routes[("files.example.com", "/cv.pdf")] = resp
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/cv.pdf")
        assert e.value.reason == reason

    def test_연결이_안_되면_network(self, web):
        with pytest.raises(FetchError) as e:
            rf.download("https://files.example.com/없는경로")
        assert e.value.reason == "network"


# ── 통합 API ─────────────────────────────────────────────────────────
class _SameSession:
    def __init__(self, db: Session):
        self._db = db

    def __enter__(self) -> Session:
        return self._db

    def __exit__(self, *exc) -> None:
        return None


class _FakeS3:
    def __init__(self):
        self.puts: list[dict] = []

    def put_object(self, **kw):
        self.puts.append(kw)


@pytest.fixture()
def env(db: Session, admin_user: User, monkeypatch, web):
    """통합 API 를 부를 준비 — 키 · 공고 · 가짜 S3 · 가짜 메일 · 요약 기록."""
    monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://test.local")
    company = db.get(CompanyProfile, 1)
    if company is None:
        company = CompanyProfile(id=1, name="테스트회사")
        db.add(company)
    posting = JobPosting(
        title="백엔드 개발자", description="본문", status="open",
        created_by=admin_user.id, public_token="posting-rf",
    )
    raw = "arda_ak_" + "r" * 32
    key = IntegrationClient(
        company_id=1, name="Workday",
        api_key_hash=bcrypt.hashpw(raw.encode(), bcrypt.gensalt(4)).decode(),
        api_key_prefix=raw[:24],
    )
    db.add_all([posting, key])
    db.commit()

    s3 = _FakeS3()
    monkeypatch.setattr("app.shared.s3._client", lambda: s3)
    monkeypatch.setattr("app.db.SessionLocal", lambda: _SameSession(db))
    published: list[int] = []
    monkeypatch.setattr("app.shared.mail.publish", lambda log_id: published.append(log_id))
    summarized: list[int] = []
    monkeypatch.setattr(rf, "after_resume", lambda app_id: summarized.append(app_id))

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    yield {
        "client": client, "db": db, "routes": web[0], "s3": s3,
        "published": published, "summarized": summarized,
        "headers": {"Authorization": f"Bearer {raw}"},
    }
    app.dependency_overrides.pop(get_db, None)


def _push(env, resume, external_id="wd-1", email="hong@example.com"):
    return env["client"].post(
        "/api/v1/integrations/applications",
        headers=env["headers"],
        json={
            "external_id": external_id,
            "posting_token": "posting-rf",
            "applicant": {
                "name": "홍길동", "email": email,
                "phone": "010-1234-5678", "birth_date": "19980315",
            },
            "resume": resume,
        },
    )


def _resumes(db, app_id):
    return db.scalars(select(File).where(File.application_id == app_id)).all()


class TestIntegrationResume:
    def test_base64_는_files_행이_되고_요약이_돈다(self, env):
        r = _push(env, {"base64": base64.b64encode(PDF).decode(), "filename": "홍길동.pdf"})
        assert r.status_code == 201, r.text
        app_id = r.json()["arda_application_id"]

        [f] = _resumes(env["db"], app_id)
        assert (f.kind, f.filename, f.content_type, f.size_bytes) == (
            "resume", "홍길동.pdf", "application/pdf", len(PDF),
        )
        assert env["s3"].puts[0]["Key"] == f.s3_key
        assert f.s3_key.startswith("applications/") and f.s3_key.endswith("/resume.pdf")
        assert env["summarized"] == [app_id]
        # 폼 접수와 같이 이력이 남는다
        assert env["db"].scalar(
            select(StageHistory).where(StageHistory.application_id == app_id)
        ).to_stage == "applied"

    def test_base64_가_이력서가_아니면_지원서도_안_남는다(self, env):
        r = _push(env, {"base64": base64.b64encode(b"MZ\x90\x00 exe").decode(), "filename": "cv.pdf"})
        assert r.status_code == 422
        assert env["db"].scalar(select(Application).where(Application.external_id == "wd-1")) is None
        assert env["s3"].puts == []

    def test_base64_크기_초과는_413(self, env, monkeypatch):
        monkeypatch.setattr("app.application.api.integrations.MAX_BYTES", 100)
        r = _push(env, {"base64": base64.b64encode(PDF).decode()})
        assert r.status_code == 413

    @pytest.mark.parametrize(
        "resume",
        [
            {"url": "https://files.example.com/cv.pdf", "base64": "JVBERg=="},
            {"filename": "cv.pdf"},
        ],
    )
    def test_url_과_base64_는_정확히_하나(self, env, resume):
        assert _push(env, resume).status_code == 422

    def test_url_을_받으면_files_행과_요약(self, env):
        env["routes"][("files.example.com", "/cv.hwp")] = _Resp(body=HWP)
        r = _push(env, {"url": "https://files.example.com/cv.hwp"})
        assert r.status_code == 201
        app_id = r.json()["arda_application_id"]

        [f] = _resumes(env["db"], app_id)
        assert (f.filename, f.content_type) == ("cv.hwp", "application/x-hwp")
        assert env["summarized"] == [app_id]
        assert env["published"] == []

    def test_url_을_못_받으면_안내_메일만_요약은_없다(self, env):
        env["routes"][("files.example.com", "/cv.pdf")] = _Resp(404)
        r = _push(env, {"url": "https://files.example.com/cv.pdf"})
        assert r.status_code == 201, "응답은 기다리지 않는다 — 받기는 뒤에서"
        app_id = r.json()["arda_application_id"]

        assert _resumes(env["db"], app_id) == []
        assert env["summarized"] == [], "이력서 없이 자동 심사가 돌면 우리 실패로 떨어진다"
        log = env["db"].scalar(select(EmailLog).where(EmailLog.application_id == app_id))
        assert log is not None, "안내 메일 행이 안 생겼다 — 제약(0025)을 확인할 것"
        assert log.stage == "resume_missing"
        assert "이력서 파일을 받지 못했습니다" in log.subject
        assert "홍길동" in log.body and "백엔드 개발자" in log.body
        assert env["published"] == [log.id]

    def test_회사가_다시_보내면_다시_받는다(self, env):
        env["routes"][("files.example.com", "/cv.pdf")] = _Resp(404)
        first = _push(env, {"url": "https://files.example.com/cv.pdf"})
        app_id = first.json()["arda_application_id"]
        assert _resumes(env["db"], app_id) == []

        env["routes"][("files.example.com", "/cv.pdf")] = _Resp(body=PDF)
        again = _push(env, {"url": "https://files.example.com/cv.pdf"})
        assert again.json() == {**first.json(), "status": "duplicate"}
        assert len(_resumes(env["db"], app_id)) == 1
        assert env["summarized"] == [app_id]

    def test_이미_이력서가_있으면_다시_받지_않는다(self, env):
        env["routes"][("files.example.com", "/cv.pdf")] = _Resp(body=PDF)
        app_id = _push(env, {"url": "https://files.example.com/cv.pdf"}).json()["arda_application_id"]
        _push(env, {"url": "https://files.example.com/cv.pdf"})
        assert len(_resumes(env["db"], app_id)) == 1
        assert len(env["s3"].puts) == 1

    def test_같은_이메일_다른_external_id_는_409_이고_DB_문구를_안_내보낸다(self, env):
        assert _push(env, None, external_id="wd-1").status_code == 201
        r = _push(env, None, external_id="wd-2")
        assert r.status_code == 409
        assert "uq_" not in r.text and "IntegrityError" not in r.text
