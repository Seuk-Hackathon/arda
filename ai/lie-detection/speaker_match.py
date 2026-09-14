"""면접 중에 들리는 목소리가 **처음 들은 그 사람인가** (2026-09-11).

지원자가 조용한 집에서 볼 수도, 시끄러운 카페에서 볼 수도 있다. 방마다 다른
바닥값을 서버가 알 길이 없으니 "소리가 크면 말" 로는 옆자리 대화·TV 가 그대로
전사에 섞인다. 그래서 **소리의 크기가 아니라 목소리의 주인**을 본다 — 답변
하나에서 지원자 목소리를 등록해 두고, 그 뒤로 그와 다른 구간만 전사에서 뺀다.

**대리응시를 잡는 장치가 아니다.** `face_match` 와 목적이 다르다. 여기서 나온
값은 판정에도, 담당자 화면에도 가지 않는다 — 전사에 들어갈 소리를 고를 뿐이다.
목소리로 사람을 가리는 판단은 억양·감기·마이크로 흔들려서 신원 확인에 쓸 것이
못 된다.

**저장하지 않는다.** 목소리 지문도 얼굴 지문과 같은 생체정보라 메모리에만 두고
면접이 끝나면 사라진다.

모델은 SpeechBrain ECAPA-TDNN (VoxCeleb) 을 ONNX 로 받은 것. 이 워커에는 torch 가
없고 앞으로도 안 넣는다 — onnxruntime 은 faster-whisper 가 이미 끌고 오는 것이라
새 의존성이 아니다. CPU 로 5초 한 번에 0.13초 걸린다(t3.large 는 이보다 느리다).
"""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "ecapa.onnx")
MEAN_PATH  = os.path.join(os.path.dirname(__file__), "models", "ecapa_mean.npy")

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2

# **5초 미만은 판정하지 않는다.** 등록에도, 대조에도 쓰지 않고 그냥 남긴다.
# 짧은 소리의 지문은 같은 사람끼리도 안 닮는다 — Zeroth-Korean 400 발화 ·
# 화자 10명 · 79,800쌍 실측(문턱 -0.10 · 본인오거부 / 남차단):
#
#     1.5초   11.97% / 45.7      3초   0.53% / 47.0
#     2.0초    2.49% / 51.0      4초   0.17% / 49.8
#                                5초   0.05% / 52.0
#
# 1.5초짜리를 판정에 넣었으면 답변마다 지원자 말이 잘렸을 것이다. 길이를 5초로
# 올리면 막는 양은 거의 그대로인데(45.7 → 52.0) 본인이 걸릴 확률만 240배 줄어든다.
MIN_SPAN_SEC = 5.0

# 코사인 유사도 문턱. 이보다 낮으면 남의 목소리로 본다 (위 표의 세로줄):
#
#     문턱     0.00    -0.05   -0.10   -0.15   -0.20
#     본인오거부 0.53%   0.15%   0.05%   0.00%   0.00%
#     남 차단   64.7%   58.8%   52.0%   43.9%   34.9%
#
# **-0.10 이다.** 원안은 0.30 이었다. 여기서 지키려는 것은 "잡음을 다 막는 것"이
# 아니라 **지원자 말을 안 자르는 것**이다 — 놓친 잡음은 담당자가 전사를 읽다
# 걸러내지만, 잘린 말은 어디에도 남지 않는다(세션 59 "첫 문장이 빠졌다").
# 0.05% 면 5초 넘는 대목 20개짜리 면접 하나에 1.0% 다.
#
# **실제 면접은 이 표와 두 군데서 다르다.** 등록과 대조가 같은 방·같은 마이크라
# 본인끼리는 표보다 더 닮을 것이고(오거부는 더 줄고), 끼어드는 사람도 같은 방
# 마이크를 타므로 남끼리도 더 닮을 것이다(차단은 더 줄고). 둘 다 안전한 쪽이
# 아니라 **덜 자르는 쪽**으로 치우친다.
REJECT_MAX = -0.10

_session = None
_mean = None
_failed = False


def _model():
    """ONNX 세션과 중심화 벡터. 없으면 None — 대조를 건너뛸 뿐 면접은 돈다."""
    global _session, _mean, _failed
    if _session is None and not _failed:
        missing = [p for p in (MODEL_PATH, MEAN_PATH) if not os.path.exists(p)]
        if missing:
            logger.warning("목소리 대조 모델이 없다 (%s) — 대조를 건너뛴다", missing)
            _failed = True
            return None, None
        import onnxruntime as ort

        _session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        _mean = np.load(MEAN_PATH)
    return _session, _mean


def available() -> bool:
    return _model()[0] is not None


def _to_float(pcm: bytes) -> np.ndarray:
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    return np.frombuffer(pcm[:usable], dtype=np.int16).astype(np.float32) / 32768.0


def embed(audio: np.ndarray) -> np.ndarray | None:
    """16kHz 모노 파형 → 192차원 목소리 지문(길이 1). 모델이 없으면 None.

    **중심화(평균 빼기)를 반드시 한다.** ECAPA 임베딩에는 "사람 목소리라면 다
    갖는" 성분이 크게 껴 있어서, 빼지 않으면 남남 평균이 +0.669 로 나와 누가
    누군지 갈리지 않는다(빼면 -0.107). 면접 하나에는 등록 지문 하나뿐이라 평균을
    그 자리에서 못 구하므로 미리 재 둔 벡터를 모델과 같이 들고 다닌다.
    """
    session, mean = _model()
    if session is None:
        return None
    vec = session.run(None, {session.get_inputs()[0].name: audio[None]})[0].reshape(-1)
    vec = vec - mean
    norm = np.linalg.norm(vec)
    return vec / norm if norm else None


# 목소리 구간을 얼마나 잘게 나눌까. **전사·`voice_seconds` 와 일부러 다르게 둔다.**
# 기본값(2초)이면 지원자가 1초 쉰 사이에 낀 옆자리 말이 지원자 말과 **한 구간**이
# 돼서, 섞인 지문이 "같은 사람" 으로 나오고 아무것도 못 뺀다. 0.5초로 잘게 끊어
# 남의 말을 따로 세워 두고, 판정은 그중 긴 것만 한다(`MIN_SPAN_SEC`).
# 앞뒤 여백(`speech_pad_ms`)은 0 — 뺄 자리를 정확히 알아야 옆 말까지 안 잘린다.
_SPLIT_SILENCE_MS = 500


def _spans(audio: np.ndarray) -> list[tuple[int, int]]:
    """목소리가 있는 구간들 (표본 번호)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    found = get_speech_timestamps(
        audio,
        VadOptions(speech_pad_ms=0, min_silence_duration_ms=_SPLIT_SILENCE_MS),
        sampling_rate=SAMPLE_RATE,
    )
    return [(s["start"], s["end"]) for s in found]


def enroll(pcm: bytes) -> np.ndarray | None:
    """이 답변에서 지원자 목소리 지문을 뜬다. 쓸 만한 게 없으면 None.

    **가장 긴 한 구간의 앞 5초만** 쓴다. 답변 전체를 넣으면 그 안에 섞인 옆자리
    소리까지 지문에 들어가는데, 그렇게 뜬 지문은 지원자와도 옆자리와도 어중간해서
    이후 판정이 통째로 흔들린다. 쉬지 않고 길게 말한 대목이 지원자 본인일
    가능성이 가장 높다.

    길이를 5초로 **고정**하는 것은 문턱값을 5초끼리 비교해서 재 놨기 때문이다
    (`MIN_SPAN_SEC`). 등록만 30초로 떠 두면 그 표가 말하는 값이 아니게 된다.
    """
    if not available():
        return None
    audio = _to_float(pcm)
    if len(audio) == 0:
        return None
    try:
        spans = _spans(audio)
    except Exception:
        logger.exception("목소리 구간 나누기 실패 — 등록을 건너뛴다")
        return None
    if not spans:
        return None
    start, end = max(spans, key=lambda s: s[1] - s[0])
    n = int(MIN_SPAN_SEC * SAMPLE_RATE)
    if (end - start) < n:
        return None
    return embed(audio[start : start + n])


def _is_other(audio: np.ndarray, start: int, end: int, ref: np.ndarray) -> bool:
    """이 구간이 등록한 사람이 **아닌가**. 애매하면 아니라고 답한다(= 안 뺀다).

    **긴 구간은 앞 5초와 뒤 5초가 둘 다 남일 때만** 남으로 본다. 구간 하나에
    두 사람이 들어 있을 수 있어서다 — 지원자 말과 끼어든 말 사이가 0.5초를
    못 넘으면 한 구간이 된다. 앞 5초만 보고 30초를 통째로 빼면 그 안의 지원자
    말까지 사라진다.
    """
    n = int(MIN_SPAN_SEC * SAMPLE_RATE)
    clips = [audio[start : start + n]]
    if (end - start) >= 2 * n:
        clips.append(audio[end - n : end])
    for clip in clips:
        vec = embed(clip)
        if vec is None or float(np.dot(vec, ref)) >= REJECT_MAX:
            return False
    return True


def filter_other(pcm: bytes, ref: np.ndarray) -> tuple[bytes, float, bool]:
    """등록한 목소리가 아닌 구간을 뺀 소리 · 뺀 초 · **전부** 남으로 보였는가.

    전부 남으로 보이면 **아무것도 빼지 않는다.** 답변 하나가 통째로 남의 것일
    확률보다 등록 지문이 잘못 떠졌을 확률이 훨씬 높다 (첫 답변에 담당자 목소리가
    섞였다든지). 그건 부른 쪽이 다시 등록할 신호로 쓴다.
    """
    audio = _to_float(pcm)
    if not available() or len(audio) == 0:
        return pcm, 0.0, False
    try:
        spans = _spans(audio)
    except Exception:
        logger.exception("목소리 구간 나누기 실패 — 자르지 않고 넘긴다")
        return pcm, 0.0, False

    judged = 0
    other: list[tuple[int, int]] = []
    for start, end in spans:
        if (end - start) < MIN_SPAN_SEC * SAMPLE_RATE:
            continue
        judged += 1
        if _is_other(audio, start, end, ref):
            other.append((start, end))

    if not other:
        return pcm, 0.0, False
    if len(other) == judged:
        return pcm, 0.0, True

    keep = np.ones(len(audio), dtype=bool)
    for start, end in other:
        keep[start:end] = False
    kept = (audio[keep] * 32768.0).astype(np.int16).tobytes()
    dropped = sum(end - start for start, end in other) / SAMPLE_RATE
    return kept, dropped, False
