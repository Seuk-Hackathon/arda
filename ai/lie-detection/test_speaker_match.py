"""목소리로 지원자와 주변 소리를 가른다 — 자르는 규칙과, 어긋났을 때의 몸사림.

여기서 틀리면 **지원자가 한 말이 전사에서 사라진다.** 세션 59("첫 문장이
빠졌다")와 같은 종류의 사고라 흔적이 안 남는다. 그래서 "언제 자르나" 보다
**"언제 안 자르나"** 를 더 많이 본다.

모델 파일(84MB)이 없어도 도는 시험이다 — 지문 뜨는 부분은 갈아 끼운다.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import app as srv
import interview_ws as iw
import speaker_match as sm

SR = sm.SAMPLE_RATE
ME = np.array([1.0, 0.0], dtype=np.float32)      # 지원자
OTHER = np.array([-1.0, 0.0], dtype=np.float32)  # 옆자리 (코사인 -1)


def pcm(seconds: float) -> bytes:
    return np.zeros(int(seconds * SR), dtype=np.int16).tobytes()


def at(*spans) -> list[tuple[int, int]]:
    """초 단위 구간 → 표본 번호 구간."""
    return [(int(a * SR), int(b * SR)) for a, b in spans]


@pytest.fixture
def fake(monkeypatch):
    """모델 없이 돌린다. `voices` 에 구간별로 누구 목소리인지 넣어 둔다."""
    box = {"spans": [], "voices": []}
    monkeypatch.setattr(sm, "available", lambda: True)
    monkeypatch.setattr(sm, "_spans", lambda audio: box["spans"])

    def embed(audio):
        i = box["seen"] = box.get("seen", -1) + 1
        return box["voices"][i]

    monkeypatch.setattr(sm, "embed", embed)
    return box


class Test자르기:
    def test_남의_구간만_빠지고_나머지는_그대로다(self, fake):
        fake["spans"] = at((0, 6), (6, 12), (12, 18))
        fake["voices"] = [ME, OTHER, ME]
        kept, dropped, all_other = sm.filter_other(pcm(18), ME)
        assert dropped == pytest.approx(6.0)
        assert all_other is False
        assert len(kept) == 12 * SR * sm.SAMPLE_WIDTH

    def test_전부_남으로_보이면_아무것도_안_자른다(self, fake):
        # 답변 하나가 통째로 남의 것일 확률보다 지문이 잘못 떠졌을 확률이 높다
        fake["spans"] = at((0, 6), (6, 12))
        fake["voices"] = [OTHER, OTHER]
        kept, dropped, all_other = sm.filter_other(pcm(12), ME)
        assert (kept, dropped, all_other) == (pcm(12), 0.0, True)

    def test_5초가_안_되는_구간은_판정하지_않는다(self, fake):
        # 짧은 소리의 지문은 같은 사람끼리도 안 닮는다 — 1.5초면 본인 오거부 12%
        fake["spans"] = at((0, 3), (3.5, 7.5))
        fake["voices"] = []            # embed 가 불리면 IndexError 로 터진다
        assert sm.filter_other(pcm(8), ME) == (pcm(8), 0.0, False)

    def test_긴_구간은_앞뒤가_둘_다_남일_때만_뺀다(self, fake):
        # 한 구간에 두 사람이 들어 있을 수 있다 — 앞 5초만 보고 20초를 빼면
        # 그 안의 지원자 말까지 사라진다
        fake["spans"] = at((0, 20), (20, 26))
        fake["voices"] = [OTHER, ME, ME]      # 20초 구간: 앞=남 뒤=본인
        assert sm.filter_other(pcm(26), ME) == (pcm(26), 0.0, False)

    def test_앞뒤가_둘_다_남이면_긴_구간도_뺀다(self, fake):
        fake["spans"] = at((0, 20), (20, 26))
        fake["voices"] = [OTHER, OTHER, ME]
        kept, dropped, all_other = sm.filter_other(pcm(26), ME)
        assert dropped == pytest.approx(20.0)
        assert len(kept) == 6 * SR * sm.SAMPLE_WIDTH

    def test_목소리가_하나도_없으면_그대로_넘긴다(self, fake):
        fake["spans"] = []
        assert sm.filter_other(pcm(3), ME) == (pcm(3), 0.0, False)


class Test등록:
    def test_가장_긴_구간의_앞_5초만_쓴다(self, fake, monkeypatch):
        # 답변 전체를 넣으면 섞인 잡음까지 지문에 들어가, 지원자와도 잡음과도
        # 어중간한 지문이 된다 — 그 뒤 판정이 통째로 흔들린다.
        # 길이를 고정하는 것은 문턱값을 5초끼리 비교해서 재 놨기 때문이다.
        fake["spans"] = at((0, 2), (2, 10), (10, 12))
        lengths = []
        monkeypatch.setattr(sm, "embed", lambda a: lengths.append(len(a)) or ME)
        assert sm.enroll(pcm(12)) is ME
        assert lengths == [5 * SR]

    def test_5초를_넘게_이어_말한_데가_없으면_안_뜬다(self, fake):
        fake["spans"] = at((0, 4), (6, 10))
        fake["voices"] = []
        assert sm.enroll(pcm(12)) is None


class Test대기줄에서:
    """`_drop_other_voice` — 어긋났을 때 몸을 사리는 쪽."""

    @pytest.fixture
    def session(self, monkeypatch):
        for k in ("voice_enrolled", "other_voice", "voice_reenrolled", "voice_disabled"):
            iw.ANSWER_STATS[k] = 0
        monkeypatch.setattr(srv, "VOICE_GATE", True)
        monkeypatch.setattr(sm, "available", lambda: True)
        return iw.InterviewSession("tok-voice")

    def run(self, session, data=b"x"):
        return asyncio.run(srv._drop_other_voice(session, data))

    def test_모델이_없으면_손대지_않는다(self, session, monkeypatch):
        monkeypatch.setattr(sm, "available", lambda: False)
        assert self.run(session) == b"x"
        assert session.voiceprint is None

    def test_스위치를_끄면_손대지_않는다(self, session, monkeypatch):
        monkeypatch.setattr(srv, "VOICE_GATE", False)
        monkeypatch.setattr(sm, "enroll", lambda p: ME)
        assert self.run(session) == b"x"
        assert session.voiceprint is None

    def test_첫_답변은_등록만_하고_그대로_넘긴다(self, session, monkeypatch):
        monkeypatch.setattr(sm, "enroll", lambda p: ME)
        assert self.run(session) == b"x"
        assert session.voiceprint is ME
        assert iw.ANSWER_STATS["voice_enrolled"] == 1

    def test_등록이_안_되면_다음_답변에_다시_해본다(self, session, monkeypatch):
        monkeypatch.setattr(sm, "enroll", lambda p: None)
        self.run(session)
        assert session.voiceprint is None
        assert iw.ANSWER_STATS["voice_enrolled"] == 0
        monkeypatch.setattr(sm, "enroll", lambda p: ME)
        self.run(session)
        assert session.voiceprint is ME

    def test_남의_목소리를_빼면_계기판에_남는다(self, session, monkeypatch):
        session.voiceprint = ME
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"cut", 2.0, False))
        assert self.run(session) == b"cut"
        assert iw.ANSWER_STATS["other_voice"] == 1

    def test_한_번_어긋난_것으로는_지문을_안_바꾼다(self, session, monkeypatch):
        session.voiceprint = ME
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"", 0.0, True))
        monkeypatch.setattr(sm, "enroll", lambda p: OTHER)
        assert self.run(session) == b"x"
        assert session.voiceprint is ME
        assert iw.ANSWER_STATS["voice_reenrolled"] == 0

    def test_연달아_어긋나면_지금_답변으로_다시_뜬다(self, session, monkeypatch):
        session.voiceprint = ME
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"", 0.0, True))
        monkeypatch.setattr(sm, "enroll", lambda p: OTHER)
        self.run(session)
        assert self.run(session) == b"x"
        assert session.voiceprint is OTHER
        assert iw.ANSWER_STATS["voice_reenrolled"] == 1
        assert session.voice_off is False

    def test_다시_떠도_어긋나면_접는다(self, session, monkeypatch):
        session.voiceprint = ME
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"", 0.0, True))
        monkeypatch.setattr(sm, "enroll", lambda p: OTHER)
        for _ in range(4):
            self.run(session)
        assert session.voice_off is True
        assert iw.ANSWER_STATS["voice_disabled"] == 1

        # 접은 뒤로는 아예 안 부른다 — 다시 켜지 않는다
        monkeypatch.setattr(sm, "filter_other", lambda p, r: 1 / 0)
        assert self.run(session) == b"x"

    def test_사이에_멀쩡한_답변이_있으면_눈금이_풀린다(self, session, monkeypatch):
        session.voiceprint = ME
        monkeypatch.setattr(sm, "enroll", lambda p: OTHER)
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"", 0.0, True))
        self.run(session)
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"ok", 0.0, False))
        self.run(session)
        monkeypatch.setattr(sm, "filter_other", lambda p, r: (b"", 0.0, True))
        self.run(session)
        assert session.voiceprint is ME
        assert iw.ANSWER_STATS["voice_reenrolled"] == 0
