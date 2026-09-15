"""답변인지는 전사가 정한다 — [답변 완료] 뒤 받아쓴 뒤에 넘기는 동작 (2026-09-15 개정).

09-11 판은 "답했다" 를 먼저 찍고 다음 질문을 보낸 뒤 전사를 뒤에서 돌렸다(CPU whisper
가 45~180초라). 그 순서는 전사가 비면 질문이 소비된 채 빈칸이 남아 앞에서 VAD 로
걸러야 했고, 그 VAD 가 앱 소리를 "목소리 0초" 로 봐서 실제 답변이 튕겼다. 전사가
API 로 옮겨 1~3초가 되면서 다시 기다린다 — 이 파일은 그 순서를 지킨다.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app as srv
import interview_ws as iw
from test_interview_ws import LOUD, QUIET

QUESTIONS = [
    {"seq": 1, "question": "첫 질문"},
    {"seq": 2, "question": "둘째 질문"},
]


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)

    def types(self):
        return [m["type"] for m in self.sent]


def _session(questions=QUESTIONS) -> iw.InterviewSession:
    s = iw.InterviewSession("tok-flow")
    s.questions = list(questions)
    for _ in range(12):
        s.add_audio(QUIET)      # 바닥값 보정
    return s


async def _speak(ws, session):
    """말하고 [답변 완료] 를 누른다. **답변은 이 버튼으로만 끝난다** (2026-09-15)."""
    for _ in range(int(iw.MIN_SPEECH_SEC / 0.05) + 2):
        session.add_audio(LOUD)
    return await srv._on_text(ws, None, session, '{"type": "end"}')


async def _pause(ws, session):
    """말했다가 멈춘다 — 감지기가 '멈춤' 을 낸다. 아무 일도 일어나지 않아야 한다."""
    session.add_audio(LOUD)                      # begin
    await asyncio.sleep(iw.MIN_SPEECH_SEC + 0.05)
    session.add_audio(QUIET)                     # 침묵 시작
    await asyncio.sleep(iw.PAUSE_CHECK_SEC + 0.05)
    await srv._on_binary(ws, None, session, bytes([srv.KIND_AUDIO]) + QUIET)


@pytest.fixture()
def saved(monkeypatch):
    """저장된 답변을 (seq, 전사) 로 모은다."""
    out = []

    async def fake_submit(client, token, transcript, seq=None):
        out.append((seq, transcript))
        return {}

    monkeypatch.setattr(srv, "submit_answer", fake_submit)
    monkeypatch.setattr(srv, "finish_interview", _noop)
    monkeypatch.setattr(srv, "mark_answered", _noop)
    return out


@pytest.fixture(autouse=True)
def _quiet_verdict(monkeypatch):
    """말하는 동안 도는 실시간 판정은 이 파일의 관심사가 아니다."""
    monkeypatch.setattr(srv, "_live_verdict", _noop)


async def _noop(*a, **kw):
    return None


def _returns(value):
    async def _fn():
        return value

    return _fn()


def _stt(text="답변입니다", delay=0.0):
    async def fake(pcm, hint=""):
        if delay:
            await asyncio.sleep(delay)
        return text

    return fake


class TestTranscriptDecides:
    """받아쓴 글이 있으면 저장하고 넘기고, 없으면 같은 질문에 다시 답하게 한다."""

    def test_전사가_비면_넘기지_않고_소리를_되돌린다(self, monkeypatch, saved):
        """세션 57(잡음이 질문 10개를 빈 답변으로 소진)을 이제는 전사 결과로 막는다."""
        async def _t():
            marked = []

            async def fake_mark(client, token, seq):
                marked.append(seq)

            monkeypatch.setattr(srv, "mark_answered", fake_mark)
            monkeypatch.setattr(srv, "transcribe_async", _stt(""))
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert ws.types() == ["processing", "retry"]
            assert marked == [] and saved == []
            assert s.current_seq() == 1
            assert s.audio, "거른 소리는 버퍼로 되돌린다 — 다시 말한 것과 합쳐진다"
        asyncio.run(_t())

    def test_전사가_있으면_저장하고_다음_질문(self, monkeypatch, saved):
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt("답변입니다"))
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert ws.types() == ["processing", "question"]
            assert ws.sent[-1] == {"type": "question", "seq": 2, "text": "둘째 질문"}
            assert saved == [(1, "답변입니다")]
            assert s.current_seq() == 2
        asyncio.run(_t())

    def test_전사를_기다린_뒤에_넘긴다(self, monkeypatch, saved):
        """다음 질문은 저장이 끝난 **뒤에** 나간다 — 그래야 빈 전사에 질문이 소비되지 않는다."""
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt("답변입니다", delay=0.3))
            ws, s = FakeWS(), _session()
            t = time.monotonic()
            await _speak(ws, s)
            assert time.monotonic() - t >= 0.3
            assert ws.types().index("question") > 0
            assert saved == [(1, "답변입니다")]
        asyncio.run(_t())

    def test_답했다_표시가_저장보다_먼저다(self, monkeypatch, saved):
        """재접속이 그 사이 지원자를 이미 답한 질문으로 되돌리지 않게 (2026-09-11 d960f9f)."""
        async def _t():
            order = []

            async def fake_mark(client, token, seq):
                order.append(("mark", seq))

            async def fake_submit(client, token, transcript, seq=None):
                order.append(("submit", seq))
                return {}

            monkeypatch.setattr(srv, "mark_answered", fake_mark)
            monkeypatch.setattr(srv, "submit_answer", fake_submit)
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert order == [("mark", 1), ("submit", 1)]
        asyncio.run(_t())

    def test_답함_표시가_실패해도_저장하고_넘긴다(self, monkeypatch, saved):
        async def _t():
            async def broken(client, token, seq):
                raise RuntimeError("백엔드가 잠깐 안 받는다")

            monkeypatch.setattr(srv, "mark_answered", broken)
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert ws.sent[-1]["type"] == "question"
            assert saved == [(1, "답변입니다")]
        asyncio.run(_t())

    def test_저장이_실패하면_넘기지_않는다(self, monkeypatch, saved):
        """넘겨 버리면 그 답은 어디에도 없다 — 소리를 되돌리고 다시 답하게 한다."""
        async def _t():
            async def broken(client, token, transcript, seq=None):
                raise RuntimeError("백엔드 5xx")

            monkeypatch.setattr(srv, "submit_answer", broken)
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert ws.sent[-1]["type"] == "retry"
            assert s.current_seq() == 1 and s.audio
        asyncio.run(_t())

    def test_저장하는_답변에서_이상입니다를_뗀다(self, monkeypatch, saved):
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt("캐시를 붙였습니다. 이상입니다."))
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert saved == [(1, "캐시를 붙였습니다.")]
        asyncio.run(_t())

    def test_이상입니다만_말하면_빈_답변이다(self, monkeypatch, saved):
        """습관적 마무리만 있으면 답이 없는 것이다 — 다시 답하게 한다."""
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt("이상입니다"))
            ws, s = FakeWS(), _session()
            await _speak(ws, s)
            assert ws.sent[-1]["type"] == "retry" and saved == []
        asyncio.run(_t())

    def test_전사_중에_또_누르면_한_번만_끝낸다(self, monkeypatch, saved):
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt(delay=0.2))
            ws, s = FakeWS(), _session()
            first = asyncio.create_task(_speak(ws, s))
            await asyncio.sleep(0.05)
            await srv._on_text(ws, None, s, '{"type": "end"}')   # 전사 도는 중에 한 번 더
            await first
            assert [m for m in ws.sent if m["type"] == "question"] == [
                {"type": "question", "seq": 2, "text": "둘째 질문"}
            ]
            assert saved == [(1, "답변입니다")]
        asyncio.run(_t())

    def test_질문_목록이_없으면_백엔드가_준_지금_질문을_쓴다(self, monkeypatch, saved):
        """서비스 토큰이 없거나 조회가 실패한 경우. 흐름은 같다."""
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            monkeypatch.setattr(
                srv, "submit_answer",
                lambda c, t, tr, seq=None: _returns({"current_question": "다음", "question_seq": 9}),
            )
            ws, s = FakeWS(), _session(questions=[])
            await _speak(ws, s)
            assert ws.types() == ["processing", "question"]
            assert ws.sent[-1]["text"] == "다음"
        asyncio.run(_t())


class TestEndOfQuestions:
    def test_마지막_질문이면_저장한_뒤_닫는다(self, monkeypatch, saved):
        """먼저 닫으면 마지막 답변이 저장되기 전에 done 이 되어 빈칸이 남는다."""
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            monkeypatch.setattr(srv, "fetch_questions", lambda c, t: _returns([QUESTIONS[1]]))
            monkeypatch.setattr(
                srv, "fetch_state",
                lambda c, t: _returns({"status": "in_progress", "question_seq": None}),
            )
            ws, s = FakeWS(), _session([QUESTIONS[1]])   # 질문 하나뿐
            await _speak(ws, s)
            assert ws.types()[-1] == "done"
            assert saved == [(2, "답변입니다")]
        asyncio.run(_t())

    def test_준비된_질문이_떨어지면_꼬리질문을_받아_이어간다(self, monkeypatch, saved):
        """꼬리질문은 전사가 저장된 뒤에 백엔드가 붙인다 — 시작 때 받은 목록에는 없다."""
        async def _t():
            tail = {"seq": 3, "question": "꼬리 질문"}
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            monkeypatch.setattr(
                srv, "fetch_questions", lambda c, t: _returns([QUESTIONS[1], tail])
            )
            monkeypatch.setattr(
                srv, "fetch_state",
                lambda c, t: _returns({"status": "in_progress", "question_seq": 3}),
            )
            ws, s = FakeWS(), _session([QUESTIONS[1]])
            await _speak(ws, s)
            assert ws.sent[-1] == {"type": "question", "seq": 3, "text": "꼬리 질문"}
            assert "done" not in ws.types()
        asyncio.run(_t())

    def test_번호를_못_찾으면_첫_질문이_아니라_끝으로_간다(self):
        """예전에는 0(첫 질문)으로 가서 이미 답한 1번을 다시 물었다."""
        qs = [{"seq": 1, "question": "a"}, {"seq": 2, "question": "b"}]
        assert srv._cursor_of(qs, 2) == 1
        assert srv._cursor_of(qs, 7) == 2
        assert srv._cursor_of(qs, None) == 2


class TestOnlyButtonEnds:
    """답변 끝은 [답변 완료] 와 상한뿐이다 (2026-09-15). 침묵도, "이상입니다" 도 아니다."""

    def test_조용해진_것만으로는_넘어가지_않는다(self, monkeypatch, saved):
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            ws, s = FakeWS(), _session()
            await _pause(ws, s)
            assert "question" not in ws.types() and "processing" not in ws.types()
            assert saved == [] and s.current_seq() == 1
            assert s.audio, "멈춘 동안의 소리도 버리지 않는다 — 이어서 말하면 한 답이 된다"
        asyncio.run(_t())

    def test_붙자마자_누르면_답변으로_세지_않는다(self, monkeypatch, saved):
        """MIN_SPEECH_SEC 도 안 쌓였으면 전사할 것도 없다 — 바로 retry."""
        async def _t():
            called = []
            monkeypatch.setattr(srv, "transcribe_async", lambda pcm, hint="": called.append(1) or _returns("x"))
            ws, s = FakeWS(), _session()
            await srv._on_text(ws, None, s, '{"type": "end"}')
            assert ws.sent[-1]["type"] == "retry" and called == []
        asyncio.run(_t())

    def test_답변이_상한을_넘으면_끊는다(self, monkeypatch, saved):
        """버튼 없이 이어지면 끝이 없다 — 상한에서 끊고 받아쓴다."""
        async def _t():
            monkeypatch.setattr(srv, "transcribe_async", _stt())
            monkeypatch.setattr(iw, "MAX_ANSWER_SEC", 0.2)
            before = iw.ANSWER_STATS["by_limit"]
            ws, s = FakeWS(), _session()
            s.add_audio(LOUD)                        # 첫 말
            await asyncio.sleep(0.25)
            await srv._on_binary(ws, None, s, bytes([srv.KIND_AUDIO]) + LOUD)
            assert ws.sent[-1] == {"type": "question", "seq": 2, "text": "둘째 질문"}
            assert iw.ANSWER_STATS["by_limit"] == before + 1
            assert saved == [(1, "답변입니다")]
        asyncio.run(_t())
