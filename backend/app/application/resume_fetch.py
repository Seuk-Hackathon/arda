"""회사 통합 API 의 이력서 받기 (ADR-0037 Phase B · 백엔드 큐 25, 2026-09-17).

회사가 `resume.url` 을 주면 **서버가 그 주소를 직접 연다.** 이 모듈의 일은 대부분
"무엇을 열지 않을 것인가" 다.

## 서버가 남의 주소를 여는 순간 생기는 문제 (SSRF)

이 서버는 EC2 위에 있다. `http://169.254.169.254/...` 을 열면 **인스턴스 권한 자격
증명**이 돌아온다. `http://localhost:8000/internal/...` 은 워커 전용 경로다. 회사
키 하나만 있으면 이런 주소를 이력서 URL 로 넣어 볼 수 있다 — 키는 회사 쪽 서버에
있고, 그 서버가 털리면 키도 털린다. 그래서:

1. **스킴은 http·https, 포트는 80·443 만.** 내부 서비스는 대개 다른 포트에 있다
2. **이름을 먼저 풀고, 나온 주소가 전부 공인 주소여야 연다.** 사설·루프백·링크로컬
   (메타데이터 주소가 여기)·CGNAT 는 거절한다. IPv6 에 싸인 IPv4 도 벗겨서 본다
3. **푼 주소로 직접 붙는다.** 확인할 때와 붙을 때 이름을 따로 풀면, 그 사이에 DNS
   응답을 바꿔(rebinding) 확인을 통과한 뒤 내부로 붙게 만들 수 있다. 그래서 소켓은
   확인한 IP 로 열고, TLS 인증서 검증만 원래 호스트 이름으로 한다
4. **리다이렉트는 따라가되 매번 1~3을 다시 한다.** 공인 주소가 내부 주소로 302 를
   던지는 것이 가장 쉬운 우회다. 최대 3번

## 받은 뒤

- **10MB 를 넘으면 거기서 끊는다.** `Content-Length` 는 거짓말할 수 있어 읽으면서도 센다
- **형식은 바이트로 판정한다.** 확장자·`Content-Type` 은 상대 서버가 붙인 값이라
  믿지 않는다. 허용 목록은 지원 폼과 같다(`files.ALLOWED_EXT` — F3)
- 저장 모양도 지원 폼과 같다 — `files` 행 하나(`kind='resume'`). 담당자 화면·요약·
  무결성 앵커가 폼으로 온 이력서와 구별하지 않고 그대로 쓴다

## 실패하면

지원자에게 「이력서를 받지 못했다」 메일을 보내고(`email_logs.stage='resume_missing'`),
**요약·자동 심사를 돌리지 않는다.** 이력서 없이 돌리면 ADR-0034 자동 심사가 우리의
내려받기 실패를 지원자 탓으로 돌려 불합격시킬 수 있다. 회사가 같은 `external_id`
로 다시 보내면 그때 다시 받는다(`integrations.py` 중복 경로).

URL 은 로그에 남기지 않는다 — 서명된 URL 이면 쿼리가 곧 열람 권한이다. 호스트만 남긴다.
"""

from __future__ import annotations

import http.client
import io
import ipaddress
import logging
import socket
import ssl
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

from sqlalchemy import select

from app.models import Application, File
from app.shared.api.files import ALLOWED_EXT, MAX_BYTES

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 15  # 소켓 동작 하나당. 연결·읽기 각각
MAX_REDIRECTS = 3
MAX_URL_LEN = 2000
ALLOWED_PORTS = frozenset({80, 443})
USER_AGENT = "Arda-ResumeFetch/1.0"

# 저장할 때 붙이는 타입. 상대가 보낸 값이 아니라 판정한 형식에서 정한다 —
# 담당자가 내려받을 때 브라우저가 이 값을 본다.
CONTENT_TYPE = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "hwp": "application/x-hwp",
    "hwpx": "application/hwp+zip",
}
assert set(CONTENT_TYPE) == set(ALLOWED_EXT)  # 허용 목록이 늘면 여기서 먼저 깨진다


class FetchError(Exception):
    """받지 못한 이유. `reason` 은 로그·테스트가 보는 짧은 코드다."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class Fetched:
    data: bytes
    ext: str
    filename: str


# ── 형식 판정 ────────────────────────────────────────────────────────
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def sniff(data: bytes) -> str | None:
    """바이트로 형식을 정한다. 허용 목록 밖이면 None.

    - pdf: `%PDF-` 로 시작
    - docx·hwpx: 둘 다 zip 이다. 안에 `word/document.xml` 이 있으면 docx,
      `mimetype` 이 `application/hwp+zip` 이면 hwpx
    - hwp: OLE 복합 문서(구 .doc 와 같은 껍데기)라 껍데기만으로는 못 가른다.
      HWP 5 는 `FileHeader` 스트림이 **압축 없이** `HWP Document File` 로 시작한다
    """
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return _sniff_zip(data)
    if data.startswith(_OLE_MAGIC) and b"HWP Document File" in data:
        return "hwp"
    return None


def _sniff_zip(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "mimetype" in names:
                # 압축 폭탄을 풀지 않도록 크기부터 본다. 정상 값은 20바이트 남짓
                if z.getinfo("mimetype").file_size > 100:
                    return None
                if z.read("mimetype").strip() == b"application/hwp+zip":
                    return "hwpx"
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        return None
    return None


# ── 주소 확인 ────────────────────────────────────────────────────────
def resolve_public(host: str, port: int) -> str:
    """이름을 풀어 **공인 주소 하나**를 돌려준다. 하나라도 내부면 거절.

    "하나라도" 인 이유: 여러 주소 중 하나만 내부여도, 붙을 때 그쪽이 골라질 수 있다.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise FetchError("dns", host) from exc
    addrs: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]  # IPv6 zone id 제거
        ip = ipaddress.ip_address(raw)
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise FetchError("blocked_host", host)
        addrs.append(str(ip))
    if not addrs:
        raise FetchError("dns", host)
    # IPv4 우선 — 서버에 IPv6 경로가 없는 경우가 흔하다
    addrs.sort(key=lambda a: ":" in a)
    return addrs[0]


class _PinnedHTTP(http.client.HTTPConnection):
    """확인한 IP 로만 붙는다. Host 헤더는 원래 이름 그대로 나간다."""

    def __init__(self, host: str, port: int, ip: str):
        super().__init__(host, port, timeout=TIMEOUT_SEC)
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """확인한 IP 로 붙고, 인증서는 원래 호스트 이름으로 검증한다."""

    def __init__(self, host: str, port: int, ip: str):
        super().__init__(host, port, timeout=TIMEOUT_SEC, context=ssl.create_default_context())
        self._pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def open_url(scheme: str, host: str, port: int, ip: str, target: str):
    """(연결, 응답). 테스트가 이 함수를 바꿔 끼워 네트워크 없이 돈다."""
    cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
    conn = cls(host, port, ip)
    conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return conn, conn.getresponse()


# ── 내려받기 ─────────────────────────────────────────────────────────
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


def download(url: str) -> Fetched:
    """URL 에서 이력서를 받는다. 못 받으면 `FetchError`."""
    if len(url) > MAX_URL_LEN:
        raise FetchError("bad_url", "too long")
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, target = _parse(current)
        ip = resolve_public(host, port)
        try:
            conn, resp = open_url(scheme, host, port, ip, target)
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError("network", type(exc).__name__) from exc
        try:
            if resp.status in _REDIRECTS:
                location = resp.getheader("Location")
                if not location:
                    raise FetchError("http_status", str(resp.status))
                current = urljoin(current, location)
                continue
            if resp.status != 200:
                raise FetchError("http_status", str(resp.status))
            data = _read_capped(resp)
            ext = sniff(data)
            if ext is None:
                raise FetchError("bad_type", resp.getheader("Content-Type") or "")
            return Fetched(data=data, ext=ext, filename=_filename(current, ext))
        finally:
            conn.close()
    raise FetchError("too_many_redirects")


def _parse(url: str) -> tuple[str, str, int, str]:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchError("bad_url", "unparsable") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("bad_url", parts.scheme or "no scheme")
    if parts.username or parts.password:
        # `https://good.com@evil.com/` 류. 사람이 읽는 호스트와 실제 호스트가 다르다
        raise FetchError("bad_url", "credentials")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchError("blocked_host", f"port {port}")
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return parts.scheme, parts.hostname, port, target


def _read_capped(resp) -> bytes:
    length = resp.getheader("Content-Length")
    if length and length.isdigit() and int(length) > MAX_BYTES:
        raise FetchError("too_large", length)
    try:
        data = resp.read(MAX_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise FetchError("network", type(exc).__name__) from exc
    if len(data) > MAX_BYTES:
        raise FetchError("too_large", f">{MAX_BYTES}")
    if not data:
        raise FetchError("empty")
    return data


def _filename(url: str, ext: str) -> str:
    """URL 마지막 조각을 파일명으로."""
    return safe_filename(unquote(urlsplit(url).path), ext)


def safe_filename(raw: str | None, ext: str) -> str:
    """상대가 준 이름을 저장용으로. 판정한 형식과 확장자가 다르면 쓰지 않는다.

    `이력서.pdf` 라고 왔는데 실제로 hwp 면, 담당자가 그 이름으로 내려받아 PDF 뷰어로
    열다 실패한다. 이름보다 내용이 맞다.
    """
    name = PurePosixPath((raw or "").replace("\\", "/")).name.strip()
    name = "".join(ch for ch in name if ch.isprintable() and ch != '"')
    if not name or PurePosixPath(name).suffix.lower() != f".{ext}":
        return f"resume.{ext}"
    return name[-255:]


# ── 저장 ─────────────────────────────────────────────────────────────
def has_resume(db, application_id: int) -> bool:
    return db.scalar(
        select(File.id).where(File.application_id == application_id, File.kind == "resume")
    ) is not None


def store(db, application_id: int, fetched: Fetched) -> File:
    """S3 에 올리고 `files` 행을 **추가만** 한다. 커밋은 호출부가 한다.

    키 모양은 지원 폼의 presign(`files._build_key`)과 같다 — 공개 접수의 키 검증
    (`public._S3_KEY`)과 앵커가 같은 모양을 전제한다.
    """
    from app.shared import s3

    key = f"applications/{uuid.uuid4()}/resume.{fetched.ext}"
    s3._client().put_object(
        Bucket=s3.BUCKET,
        Key=key,
        Body=fetched.data,
        ContentType=CONTENT_TYPE[fetched.ext],
    )
    row = File(
        application_id=application_id,
        s3_key=key,
        filename=fetched.filename,
        size_bytes=len(fetched.data),
        content_type=CONTENT_TYPE[fetched.ext],
        kind="resume",
    )
    db.add(row)
    db.flush()
    return row


def after_resume(application_id: int) -> None:
    """이력서가 생긴 뒤에 도는 것 — 지원 폼 접수와 같은 둘."""
    from app.agent.summarizer import generate_summary_bg
    from app.shared.anchoring import anchor_application_bg

    generate_summary_bg(application_id)
    anchor_application_bg(application_id)


# ── 백그라운드 진입점 ───────────────────────────────────────────────
def fetch_resume_bg(application_id: int, url: str) -> None:
    """FastAPI BackgroundTasks 용. 받으면 요약·앵커까지, 못 받으면 안내 메일."""
    from app.db import SessionLocal

    host = urlsplit(url).hostname or "?"
    with SessionLocal() as db:
        app = db.get(Application, application_id)
        if app is None or has_resume(db, application_id):
            return  # 그 사이 다른 요청이 받았다
        try:
            fetched = download(url)
        except FetchError as exc:
            logger.warning(
                "이력서 내려받기 실패: application=%s host=%s reason=%s",
                application_id, host, exc.reason,
            )
            send_missing_mail(db, app)
            return
        try:
            store(db, application_id, fetched)
            db.commit()
        except Exception:
            # 우리 쪽(S3·DB) 실패다. 지원자에게 "파일이 잘못됐다" 고 말할 일이 아니다.
            # 회사가 다시 보내면 다시 받는다.
            db.rollback()
            logger.exception("이력서 저장 실패: application=%s host=%s", application_id, host)
            return
    logger.info(
        "이력서 받음: application=%s host=%s ext=%s bytes=%s",
        application_id, host, fetched.ext, len(fetched.data),
    )
    after_resume(application_id)


def send_missing_mail(db, app: Application) -> None:
    """「이력서를 받지 못했다」 안내. 실패해도 삼킨다 — 로그가 남는다."""
    from app.shared import mail

    try:
        log = mail.create_log(db, app.id, app.email, "resume_missing")
        log.subject, log.body = mail.render_resume_missing(db, app)
        db.commit()
        mail.publish(log.id)
    except Exception:
        db.rollback()
        logger.exception("이력서 누락 안내 메일 실패: application=%s", app.id)
