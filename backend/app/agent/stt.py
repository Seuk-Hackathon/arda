"""음성-텍스트 변환 (STT).

마이크 녹음 → 전사 → entity_resolver 전처리 → 에이전트 입력.

백엔드가 둘이다 (`STT_BACKEND`, 기본 `openai` — 미설정이면 지금까지와 동일):

- `openai`         : OpenAI Whisper API. `OPENAI_API_KEY` 필요, 오디오가 외부로 나간다
- `faster_whisper` : 로컬 전사. 외부 호출 0건, 비용 0

로컬 백엔드를 쓰려면 별도 설치가 필요하다 — `uv sync --extra local`.
운영 API 서버(t3.micro)에 기본으로 깔리면 안 되므로 optional 로 뺐다.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time

from app.agent.entity_resolver import resolve_entities

logger = logging.getLogger(__name__)

# **빈 값도 기본값으로 본다** (2026-09-16). `os.getenv(…, "openai")` 는 변수가
# "있고 비어 있으면" 기본값을 안 쓴다 — 그러면 빈 문자열이 오타와 같은 취급이 되어
# 전사 경로가 통째로 죽는다. 운영에서 실제로 그랬다: `.env` 에 `STT_BACKEND=` 로
# 비워 두자 업로드 답변·재전사·아르 음성 입력이 전부 503/502 였다(실측 2026-09-16).
#
# 같은 변수를 lie-detection 도 읽는데 **그쪽은 빈 값을 「로컬 전사」로 읽는다**
# (ADR-0038 결정 4). 여기서 그 해석을 따라가지 않는 이유는 **백엔드 이미지에 로컬
# 모델이 없어서**다(`Dockerfile` 이 `--extra local` 없이 설치한다) — 맞춰 봐야 다른
# 에러가 날 뿐이다. 오디오를 밖으로 안 내보내려면 `faster_whisper` 를 **명시**한다.
STT_BACKEND = (os.getenv("STT_BACKEND", "openai").strip().lower() or "openai")

# whisper-1 은 무음·잡음에도 말을 지어낸다 — 유튜브 자막 문구("다음 영상에서
# 만나요")가 답변으로 저장된 사고가 있었다(2026-09-15, 수택님 실측). API 에는
# 로컬의 `vad_filter` 가 없어서 `verbose_json` 의 조각마다 오는 `no_speech_prob`
# 로 거른다 — lie-detection 이 쓰는 값과 같은 이름·같은 기본값이다.
STT_NO_SPEECH_MAX = float(os.getenv("STT_NO_SPEECH_MAX", "0.6"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
WHISPER_PRICE_PER_MINUTE = 0.006

# 로컬 전사 설정. large-v3-turbo 는 large-v3 와 같은 인코더에 디코더를 4층으로
# 줄인 것이라 훨씬 빠르고 가볍다(ADR-0032). 개발 PC CPU 에서 int8 로 실측:
# 35.6초 음성 → 19.5초, 메모리 ~1.0GB.
LOCAL_MODEL = os.getenv("WHISPER_LOCAL_MODEL", "large-v3-turbo")
LOCAL_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
LOCAL_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")

# 모델 로드는 비싸다(수 초 ~ 수십 초). 한 번 올려 두고 재사용한다.
# 락은 로드 구간만 감싼다 — 두 요청이 동시에 들어와 모델을 두 번 올리면 VRAM 이 두 배로 든다.
_local_model = None
_local_lock = threading.Lock()


def backend_tag() -> str:
    """로그·응답에 남길 식별자. 모델명만 남기면 어느 엔진이 만든 값인지 알 수 없다."""
    if STT_BACKEND == "faster_whisper":
        return f"faster-whisper:{LOCAL_MODEL}"
    return f"openai:{WHISPER_MODEL}"


def _estimate_stt_cost(audio_duration_sec: float) -> float:
    """API 전사 비용(USD) 추정. 로컬 전사는 부르지 않는다 — 0 이다."""
    return audio_duration_sec / 60.0 * WHISPER_PRICE_PER_MINUTE


def _get_local_model():
    global _local_model
    if _local_model is not None:
        return _local_model
    with _local_lock:
        if _local_model is not None:
            return _local_model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - 설치 안내 경로
            raise RuntimeError(
                "faster-whisper 가 설치되지 않았습니다. `uv sync --extra local` 로 설치하세요"
            ) from exc
        logger.info("로컬 STT 모델 로딩: %s (%s)", LOCAL_MODEL, LOCAL_DEVICE)
        _local_model = WhisperModel(
            LOCAL_MODEL, device=LOCAL_DEVICE, compute_type=LOCAL_COMPUTE_TYPE
        )
        return _local_model


def _transcribe_openai(audio_bytes: bytes, filename: str) -> tuple[str, float]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes),
        language="ko",
        response_format="verbose_json",
    )
    return (
        _text_without_silence(response),
        (getattr(response, "duration", 0.0) or 0.0),
    )


def _text_without_silence(response) -> str:
    """무음에 지어낸 조각을 뺀 글 (2026-09-16).

    `verbose_json` 은 조각(segment)마다 `no_speech_prob` 를 준다. `STT_NO_SPEECH_MAX`
    이상인 조각은 버린다 — 그게 로컬 `vad_filter` 를 대신한다.

    **조각 정보가 없으면 `text` 를 그대로 쓴다.** 모델·형식이 바뀌어 조각이 안 와도
    답변을 잃지는 않는다 — 거르지 못할 뿐이다.
    """
    segments = getattr(response, "segments", None)
    if not segments:
        return (getattr(response, "text", "") or "").strip()

    kept = []
    for seg in segments:
        prob = getattr(seg, "no_speech_prob", None)
        if prob is None and isinstance(seg, dict):
            prob = seg.get("no_speech_prob")
        text = getattr(seg, "text", None)
        if text is None and isinstance(seg, dict):
            text = seg.get("text")
        if prob is not None and prob >= STT_NO_SPEECH_MAX:
            logger.info("무음 조각을 버린다 (no_speech_prob=%.2f)", prob)
            continue
        if text:
            kept.append(text.strip())
    return " ".join(kept).strip()


def _transcribe_local(audio_bytes: bytes) -> tuple[str, float]:
    """로컬 전사. 오디오가 이 프로세스를 벗어나지 않는다."""
    model = _get_local_model()
    # faster-whisper 는 경로 대신 바이너리 파일 객체를 받는다 — 임시 파일을 안 만든다
    segments, info = model.transcribe(
        io.BytesIO(audio_bytes),
        language="ko",
        # **로컬도 무음에 말을 지어낸다** (2026-09-16). 실측에서 무음 3초·잡음 3초가
        # 모두 "감사합니다." 를 냈다(lie-detection 쪽 기록). VAD 로 말이 없는 구간을
        # 먼저 잘라내면 낼 조각 자체가 없어진다.
        vad_filter=True,
        # 앞 조각을 참고하면 한 번 지어낸 말이 뒤로 번진다.
        condition_on_previous_text=False,
    )
    # segments 는 제너레이터다. 여기서 소비해야 전사가 실제로 돈다
    text = "".join(seg.text for seg in segments).strip()
    return text, float(getattr(info, "duration", 0.0) or 0.0)


def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """오디오 바이트를 전사하고 엔티티 해석을 적용한다.

    Returns:
        {"raw": 원본 전사, "resolved": 전처리 결과,
         "duration_ms": 처리 시간, "audio_duration_sec": 오디오 길이,
         "cost_usd": 추정 비용}

    반환 계약은 백엔드와 무관하게 같다 — 화면(SttResponse)이 이 형태에 묶여 있다.
    """
    if STT_BACKEND not in ("openai", "faster_whisper"):
        # 조용히 openai 로 폴백하지 않는다. 오타 하나로 오디오가 외부로 나가면 안 된다
        raise RuntimeError(
            f"알 수 없는 STT_BACKEND: {STT_BACKEND} (가능: openai, faster_whisper)"
        )

    start = time.monotonic()
    if STT_BACKEND == "faster_whisper":
        raw_text, audio_duration_sec = _transcribe_local(audio_bytes)
        cost = 0.0
    else:
        raw_text, audio_duration_sec = _transcribe_openai(audio_bytes, filename)
        cost = _estimate_stt_cost(audio_duration_sec)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    resolved_text = resolve_entities(raw_text)

    logger.info(
        "stt_transcribe",
        extra={
            "backend": STT_BACKEND,
            "model": backend_tag(),
            "raw_length": len(raw_text),
            "resolved_length": len(resolved_text),
            "duration_ms": elapsed_ms,
            "audio_duration_sec": round(audio_duration_sec, 2),
            "cost_usd": round(cost, 6),
        },
    )

    return {
        "raw": raw_text,
        "resolved": resolved_text,
        "duration_ms": elapsed_ms,
        "audio_duration_sec": round(audio_duration_sec, 2),
        "cost_usd": round(cost, 6),
    }
