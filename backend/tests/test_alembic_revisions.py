"""alembic 리비전 번호가 겹치지 않고 한 줄로 이어지는가 (2026-09-17).

**CI 가 초록인 채로 main 이 깨졌던 자리다.** #282 가 `0023` 을 새로 만들었는데 `0023`
은 이미 있었다. alembic 은 경고만 내고 한쪽을 고르고, 테스트는 `create_all` 로 표를
만들어서 아무것도 안 걸렸다 — 운영 DB 에서만 표가 안 생긴다.

DB 없이 파일만 읽는다. 번호를 짓는 사람이 두 명 이상이면 언제든 다시 난다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
# `revision = "0002"` 와 `revision: str = '0001'`(타입 표기) 둘 다 있다
_REV = re.compile(r'^revision(?:\s*:[^=\n]+)?\s*=\s*["\']([^"\']+)["\']', re.M)
_DOWN = re.compile(r'^down_revision(?:\s*:[^=\n]+)?\s*=\s*(None|["\']([^"\']+)["\'])', re.M)


def _revisions() -> dict[str, tuple[str, str | None]]:
    """파일명 → (revision, down_revision)."""
    out = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        rev = _REV.search(text)
        down = _DOWN.search(text)
        assert rev and down, f"{path.name}: revision/down_revision 을 못 읽었다"
        out[path.name] = (rev.group(1), down.group(2))
    return out


def test_리비전_번호가_겹치지_않는다():
    counts = Counter(rev for rev, _ in _revisions().values())
    dup = {rev: [n for n, (r, _) in _revisions().items() if r == rev]
           for rev, c in counts.items() if c > 1}
    assert not dup, f"같은 번호를 두 파일이 쓴다 — 뒤에 온 것을 맨 끝 번호로 옮길 것: {dup}"


def test_갈래_없이_한_줄이다():
    revs = _revisions().values()
    ids = {rev for rev, _ in revs}
    parents = Counter(down for _, down in revs if down is not None)
    heads = ids - set(parents)
    assert len(heads) == 1, f"head 가 {len(heads)}개: {sorted(heads)}"
    branched = {p: c for p, c in parents.items() if c > 1}
    assert not branched, f"한 리비전에서 두 갈래로 나뉜다: {branched}"
    assert sum(1 for _, down in revs if down is None) == 1, "시작점(down_revision=None)이 하나가 아니다"
