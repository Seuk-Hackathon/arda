"""앱 전용 DB 롤(`arda_app`) 권한을 맞춘다 — 매 배포마다 돌려도 같은 결과 (이슈 #7 · ADR-0028).

**무엇을 하나 — 쉬운 말로**: 앱이 DB 에 관리자로 붙으면, 지워지면 안 되는 제출물 지문
장부(`document_anchors`)의 잠금을 앱이 스스로 풀 수 있다. 그래서 앱에게는 **평범한 표는
읽기·쓰기, 장부는 넣기·읽기만** 주는 전용 롤을 쓰게 한다. 이 스크립트는 그 권한을
관리자 연결로 맞춘다.

**왜 이행 파일(alembic)이 아니라 스크립트인가**: 이행은 한 번 지나가면 다시 돌지 않는다.
`0007` 이 그랬다 — 운영 DB 가 이미 `0007` 을 지난 뒤라 `ARDA_APP_DB_ROLE` 을 넣어도
장부 권한 회수가 영영 실행되지 않는다. 같은 일을 새 이행으로 옮겨도, 롤을 켜기 전에
배포되면 똑같이 빈손으로 지나간다. 이 스크립트는 **배포 때마다 이행 다음에** 돌고, 여러 번
돌려도 결과가 같다. 롤을 언제 켜든 그다음 배포부터 맞는다.

**새 표 문제**: `GRANT ... ON ALL TABLES` 는 그 순간 있는 표에만 준다. 그래서
`ALTER DEFAULT PRIVILEGES` 로 **관리자가 앞으로 만드는 표·시퀀스에도** 자동으로 붙게 한다.
(매 배포 재실행이 이중 안전망이다.)

환경변수
- `ARDA_APP_DB_ROLE` — 앱 롤 이름. **비었으면 아무것도 안 하고 0 으로 끝난다**(분리 전 환경)
- `MIGRATION_DATABASE_URL` → 없으면 `DATABASE_URL` — **관리자** 연결. 앱 롤로 붙어 있으면 실패

종료 코드: 0 정상 · 1 설정 오류 또는 적용 뒤 검사 실패(배포를 멈춰야 하는 상태)

사용 (backend/ 에서):
    ARDA_APP_DB_ROLE=arda_app MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:...@db:5432/arda \
      uv run python scripts/apply_db_privileges.py
"""

from __future__ import annotations

import os
import re

from sqlalchemy import create_engine, text

LEDGER = "document_anchors"
# 앱이 고치면 안 되는 표. 이행 기록은 관리자만 쓴다.
READ_ONLY = {"alembic_version"}
_ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def apply(conn, role: str) -> None:
    r = _q(role)
    db = conn.execute(text("select current_database()")).scalar()
    admin = conn.execute(text("select current_user")).scalar()
    stmts = [
        f"GRANT CONNECT ON DATABASE {_q(db)} TO {r}",
        f"GRANT USAGE ON SCHEMA public TO {r}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {r}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {r}",
        # 앞으로 관리자(= 이행을 돌리는 롤)가 만드는 표·시퀀스
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {_q(admin)} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {_q(admin)} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {r}",
        # 장부 — 넣기·읽기만. 고치기·지우기·비우기는 권한 자체가 없다
        f"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE {LEDGER} FROM {r}",
        f"GRANT SELECT, INSERT ON TABLE {LEDGER} TO {r}",
    ]
    for t in READ_ONLY:
        stmts.append(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE {t} FROM {r}")
        stmts.append(f"GRANT SELECT ON TABLE {t} TO {r}")
    for s in stmts:
        conn.execute(text(s))


def verify(conn, role: str) -> list[str]:
    """적용 결과를 표마다 확인한다. 문제 목록을 돌려준다."""
    problems = []
    tables = conn.execute(text(
        "select tablename from pg_tables where schemaname = 'public' order by 1"
    )).scalars().all()

    def has(t: str, priv: str) -> bool:
        return bool(conn.execute(
            text("select has_table_privilege(:r, :t, :p)"),
            {"r": role, "t": f"public.{t}", "p": priv},
        ).scalar())

    for t in tables:
        if t == LEDGER:
            for p in ("SELECT", "INSERT"):
                if not has(t, p):
                    problems.append(f"{t}: {p} 이 없다 — 접수 때 지문을 못 남긴다")
            for p in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                if has(t, p):
                    problems.append(f"{t}: {p} 이 남아 있다 — 장부를 앱이 고칠 수 있다")
        elif t in READ_ONLY:
            if not has(t, "SELECT"):
                problems.append(f"{t}: SELECT 이 없다")
        else:
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if not has(t, p):
                    problems.append(f"{t}: {p} 이 없다 — 이 표를 쓰는 기능이 멈춘다")

    owner_is_role = conn.execute(text(
        "select count(*) from pg_tables where schemaname='public' and tableowner = :r"
    ), {"r": role}).scalar()
    if owner_is_role:
        problems.append(f"앱 롤이 표 {owner_is_role}개의 소유자다 — 소유자는 잠금을 끌 수 있다")

    super_or_bypass = conn.execute(text(
        "select rolsuper or rolbypassrls from pg_roles where rolname = :r"
    ), {"r": role}).scalar()
    if super_or_bypass:
        problems.append("앱 롤이 슈퍼유저다 — 권한 분리가 의미 없다")
    return problems


def main() -> int:
    role = (os.getenv("ARDA_APP_DB_ROLE") or "").strip()
    if not role:
        print("ARDA_APP_DB_ROLE 이 비어 있다 — 앱과 관리자 롤을 가르지 않은 환경. 건너뛴다")
        return 0
    if not _ROLE_NAME.fullmatch(role):
        print(f"ARDA_APP_DB_ROLE 모양이 이상하다: {role!r}")
        return 1
    url = os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL(또는 DATABASE_URL) 이 필요하다")
        return 1

    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        me = conn.execute(text("select current_user")).scalar()
        if me == role:
            print(
                f"앱 롤({role})로 붙어 있다 — 권한은 관리자만 줄 수 있다. "
                "MIGRATION_DATABASE_URL 을 관리자 연결로 넣어라"
            )
            return 1
        exists = conn.execute(
            text("select 1 from pg_roles where rolname = :r"), {"r": role}
        ).scalar()
        if not exists:
            print(f"롤 {role} 이 DB 에 없다 — 절차서 1단계(CREATE ROLE)를 먼저 한다")
            return 1
        apply(conn, role)
        problems = verify(conn, role)

    if problems:
        print(f"권한 적용 뒤 검사 실패 — {len(problems)}건")
        for p in problems:
            print("  ✗", p)
        return 1
    print(f"{role} 권한 확인 — 일반 표 읽기·쓰기 · {LEDGER} 넣기·읽기만 · 새 표 기본 권한 설정됨")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
