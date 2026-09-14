"""역합성 — 시드의 뼈대(tool_calls + reply 의도) 는 유지하고 사용자 발화만
**극단적으로 다양화** 한다.

## synth_expand.py 와의 차이

`synth_expand.py` 는 "동일한 의도 · 다른 표현" (완만한 확장) 이라 생성된 변형이
서로 비슷하다. 실제 사용자는 훨씬 다양하게 말한다:

- 짧게: "김도현" (한 마디)
- 길게: "혹시 김도현이라는 이름의 지원자가 우리 회사에 지원했는지 좀 알려 주실 수 있나요?"
- 캐주얼: "김도현 있어?"
- 정중: "김도현 님의 지원 여부를 확인 부탁드립니다"
- 우회: "김씨 성 가진 서울대 출신 있으면 좀"
- 오타/약어: "김도현찾아쥐"

역합성은 이런 diversity 를 명시적으로 요청한다. 같은 도구 호출을 유발하지만
사용자 발화 자체가 매우 다른 케이스를 만든다.

## 산출물

`synth_reverse.jsonl` — 같은 JSON 스키마 (build_dataset.py 가 그대로 받아 병합).
`_pass` 필드는 `reverse-N` 로 시작해서 `synth_expand.py` 결과와 구분 가능.

## 사용

    python synth_reverse.py                                # 기본 pass=reverse-0 · 발화 15개
    UTTERANCES_PER_SEED=20 REVERSE_PASS=1 python synth_reverse.py

## 비용

시드 47 × 15 발화 × 2 pass = ~1,400건 · 예상 $10~15.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

try:
    from anthropic import Anthropic
except ImportError:
    print("anthropic 패키지 필요 · pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def _load_dotenv() -> None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env_path = Path(__file__).parent.parent.parent / "backend" / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()

SEED_PATH = Path(__file__).parent / "synth_seed.yaml"
OUT_PATH = Path(__file__).parent / "synth_reverse.jsonl"
CACHE_PATH = Path(__file__).parent / ".synth_reverse_cache.jsonl"

MODEL = "claude-haiku-4-5-20251001"
UTTERANCES_PER_SEED = int(os.getenv("UTTERANCES_PER_SEED", "15"))
REVERSE_PASS = f"reverse-{os.getenv('REVERSE_PASS', '0')}"
MAX_TOKENS = 3000  # 발화만 짧게 여러 개라 원래 확장보다 여유 필요

REVERSE_PROMPT = """\
당신은 채용 ATS 의 AI 어시스턴트 "아르" 학습 데이터를 만든다.

아래 시드가 정의한 **의도·도구 호출·응답** 은 그대로 두고, **사용자 발화만 {n}가지로
극단적으로 다양화** 하라. 목표는 실제 사용자의 다양한 어투를 모두 커버해서 모델이
같은 도구 호출을 다양한 표현에서 인식하게 만드는 것.

발화 다양성 규칙 (반드시 여러 유형 섞기):

1. **짧게** (한 마디 · 1~5어)
2. **길게** (한 문장 20자+)
3. **캐주얼** (반말 톤, 축약)
4. **정중** ("~해 주실 수 있나요")
5. **우회적** (성/부서/직군 등으로 지목)
6. **약어/오타** (자연스러운 실수 · 지나치지 않게)
7. **여러 정보 섞음** (한 발화에 이름+공고+요청)
8. **명령형 · 문의형 · 감탄형** 섞음

각 발화는 반드시 시드의 tool_calls 를 그대로 유발해야 한다 — 도구·인자·의도 유지.

시드:
```yaml
{seed}
```

응답 형식 — **JSON 만**:
{{"utterances": ["발화1", "발화2", ..., "발화{n}"]}}

주의:
- 실제 사람 이름·회사명 넣지 마라.
- reply·tool_calls 는 시드 그대로 재사용 (수정하지 마라).
- 지원자·회사 정보를 새로 지어내지 마라 — 시드 기준.
"""


def load_seeds() -> list[dict[str, Any]]:
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    return data["seeds"]


def load_cache() -> set[tuple[str, str]]:
    if not CACHE_PATH.exists():
        return set()
    done = set()
    for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            done.add((case["_seed_id"], case.get("_pass", "reverse-0")))
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def generate_utterances(client: Anthropic, seed: dict[str, Any]) -> list[str]:
    """Haiku 에게 시드 하나에서 다양한 발화만 뽑는다 (tool_calls·reply 재사용)."""
    prompt = REVERSE_PROMPT.format(
        n=UTTERANCES_PER_SEED,
        seed=yaml.dump(seed, allow_unicode=True, sort_keys=False),
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if hasattr(block, "text"))

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"JSON 못 찾음: {text[:200]}")
    payload = json.loads(text[start : end + 1])
    return list(payload.get("utterances", []))


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 없음", file=sys.stderr)
        return 1

    client = Anthropic()
    seeds = load_seeds()
    done = load_cache()
    print(
        f"[reverse] 시드 {len(seeds)}건 · 이미 처리 {len(done)}건 "
        f"· pass={REVERSE_PASS} · 발화={UTTERANCES_PER_SEED}",
        file=sys.stderr,
    )

    out_mode = "a" if CACHE_PATH.exists() else "w"
    cache_f = CACHE_PATH.open(out_mode, encoding="utf-8")

    total = 0
    for i, seed in enumerate(seeds, 1):
        sid = seed["id"]
        if (sid, REVERSE_PASS) in done:
            print(f"[reverse] ({i}/{len(seeds)}) {sid} 스킵 (pass={REVERSE_PASS})", file=sys.stderr)
            continue

        try:
            utterances = generate_utterances(client, seed)
        except Exception as exc:
            print(f"[reverse] ({i}/{len(seeds)}) {sid} 실패: {exc}", file=sys.stderr)
            time.sleep(2)
            continue

        # 시드의 도구·응답 재사용해서 각 발화마다 케이스 하나씩 만든다.
        seed_tool_calls = seed.get("tool_calls", [])
        seed_reply = seed.get("reply") or seed.get("reply_pattern") or ""
        seed_pending = bool(seed.get("pending_action"))
        seed_history = seed.get("history")

        for utt in utterances:
            case = {
                "input": utt,
                "tool_calls": seed_tool_calls,
                "reply": seed_reply,
                "pending_action": seed_pending,
                "_seed_id": sid,
                "_category": seed["category"],
                "_pass": REVERSE_PASS,
            }
            if seed_history:
                case["history"] = seed_history
            cache_f.write(json.dumps(case, ensure_ascii=False) + "\n")

        cache_f.flush()
        total += len(utterances)
        print(f"[reverse] ({i}/{len(seeds)}) {sid} → {len(utterances)}건 (pass={REVERSE_PASS})", file=sys.stderr)
        time.sleep(0.5)

    cache_f.close()

    # 최종 산출물 — build_dataset.py 는 두 파일 다 병합할 수 있어야 함 (다음 커밋).
    OUT_PATH.write_text(CACHE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[reverse] 총 {total}건 신규 → {OUT_PATH} (누적 · pass={REVERSE_PASS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
