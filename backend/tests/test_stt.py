"""STT 모듈 테스트 — OpenAI Whisper 를 mock 해서 단위 검증."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from app.agent.stt import _estimate_stt_cost, transcribe


@dataclass
class FakeTranscription:
    text: str = ""
    duration: float = 10.0


class TestTranscribeNoKey:
    """OPENAI_API_KEY 가 없으면 RuntimeError."""

    def test_raises_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                transcribe(b"dummy_audio")


class TestTranscribeWithMock:
    """OpenAI 클라이언트를 mock 해서 정상 동작 검증."""

    def _run(self, raw_text: str, filename: str = "audio.webm") -> dict:
        fake_resp = FakeTranscription(text=raw_text)
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = fake_resp

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            return transcribe(b"fake_audio_bytes", filename)

    def test_return_keys(self):
        result = self._run("안녕하세요")
        assert "raw" in result
        assert "resolved" in result
        assert "duration_ms" in result
        assert "audio_duration_sec" in result
        assert "cost_usd" in result

    def test_raw_matches_whisper_output(self):
        result = self._run("  김도현 파이썬 이년 경력  ")
        assert result["raw"] == "김도현 파이썬 이년 경력"

    def test_entity_resolution_applied(self):
        result = self._run("파이썬 이년 이상")
        assert "Python" in result["resolved"]
        assert "2년" in result["resolved"]

    def test_tech_term_resolved(self):
        result = self._run("리액트 개발자")
        assert "React" in result["resolved"]

    def test_duration_is_non_negative(self):
        result = self._run("테스트")
        assert result["duration_ms"] >= 0

    def test_custom_filename_passed(self):
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = FakeTranscription(text="ok")

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            transcribe(b"audio", filename="recording.wav")

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["file"] == ("recording.wav", b"audio")

    def test_korean_language_used(self):
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = FakeTranscription(text="ok")

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            transcribe(b"audio")

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["language"] == "ko"

    def test_verbose_json_format(self):
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = FakeTranscription(text="ok")

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            transcribe(b"audio")

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["response_format"] == "verbose_json"

    def test_empty_text(self):
        result = self._run("   ")
        assert result["raw"] == ""
        assert result["resolved"] == ""


class TestSttCost:
    """STT 비용 추정 검증."""

    def test_one_minute(self):
        assert _estimate_stt_cost(60.0) == pytest.approx(0.006)

    def test_ten_seconds(self):
        assert _estimate_stt_cost(10.0) == pytest.approx(0.001)

    def test_zero(self):
        assert _estimate_stt_cost(0.0) == 0.0

    def test_cost_in_result(self):
        fake_resp = FakeTranscription(text="테스트", duration=30.0)
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = fake_resp

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            result = transcribe(b"audio")

        assert result["audio_duration_sec"] == 30.0
        assert result["cost_usd"] == pytest.approx(0.003)


class TestTranscribeKeyPresent:
    """키가 있을 때 임포트-레벨 동작."""

    def test_openai_client_created_with_key(self):
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = FakeTranscription(text="ok")

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test123"}),
            patch("openai.OpenAI", return_value=mock_client) as mock_cls,
        ):
            transcribe(b"audio")

        mock_cls.assert_called_once_with(api_key="sk-test123")


# ── 백엔드 분기 (2026-09-01) ──────────────────────────────────────
# STT_BACKEND 는 import 시점에 읽는 모듈 상수라 patch.dict 로는 안 바뀐다.
# 모듈 속성을 직접 갈아 끼운다.

class TestBackendDispatch:
    """STT_BACKEND 로 openai / faster_whisper 를 가른다. 기본값은 openai."""

    def test_기본값은_openai(self):
        from app.agent import stt
        assert stt.STT_BACKEND == "openai"
        assert stt.backend_tag().startswith("openai:")

    def test_모르는_백엔드는_조용히_폴백하지_않는다(self):
        """오타 하나로 오디오가 외부로 나가면 안 된다 — 터뜨린다."""
        from app.agent import stt
        with patch.object(stt, "STT_BACKEND", "openai_typo"):
            with pytest.raises(RuntimeError, match="알 수 없는 STT_BACKEND"):
                stt.transcribe(b"dummy")

    def test_로컬_백엔드는_openai_를_부르지_않는다(self):
        from app.agent import stt

        fake_seg = MagicMock()
        fake_seg.text = "면접 단계 지원자 보여줘"
        fake_info = MagicMock()
        fake_info.duration = 4.0
        fake_model = MagicMock()
        fake_model.transcribe.return_value = (iter([fake_seg]), fake_info)

        with (
            patch.object(stt, "STT_BACKEND", "faster_whisper"),
            patch.object(stt, "_get_local_model", return_value=fake_model),
            patch("openai.OpenAI", side_effect=AssertionError("외부 API 를 불렀다")),
        ):
            result = stt.transcribe(b"dummy_audio")

        assert result["raw"] == "면접 단계 지원자 보여줘"
        assert result["audio_duration_sec"] == 4.0

    def test_로컬_전사는_비용이_0이다(self):
        from app.agent import stt

        fake_seg = MagicMock()
        fake_seg.text = "안녕하세요"
        fake_info = MagicMock()
        fake_info.duration = 600.0  # 10분 — API 였다면 $0.06 이 붙는다
        fake_model = MagicMock()
        fake_model.transcribe.return_value = (iter([fake_seg]), fake_info)

        with (
            patch.object(stt, "STT_BACKEND", "faster_whisper"),
            patch.object(stt, "_get_local_model", return_value=fake_model),
        ):
            result = stt.transcribe(b"dummy_audio")

        assert result["cost_usd"] == 0.0

    def test_로컬_태그에_엔진이_박힌다(self):
        """모델명만 남기면 어느 엔진이 만든 값인지 로그에서 알 수 없다."""
        from app.agent import stt
        with (
            patch.object(stt, "STT_BACKEND", "faster_whisper"),
            patch.object(stt, "LOCAL_MODEL", "large-v3"),
        ):
            assert stt.backend_tag() == "faster-whisper:large-v3"


class TestEmptyBackendEnv:
    """**빈 값도 기본값으로 본다** (2026-09-16).

    `os.getenv(…, "openai")` 는 변수가 "있고 비어 있으면" 기본값을 안 쓴다. 운영
    `.env` 에 `STT_BACKEND=` 로 비워 두자 **전사 경로가 통째로 죽었다** — 업로드
    답변·재전사·아르 음성 입력이 전부 503/502 였고, 요청 로그에만 남아 아무도
    몰랐다(2026-09-16 실측).
    """

    def test_빈_문자열이면_openai_로_읽는다(self, monkeypatch):
        import importlib

        from app.agent import stt

        monkeypatch.setenv("STT_BACKEND", "")
        reloaded = importlib.reload(stt)
        try:
            assert reloaded.STT_BACKEND == "openai"
        finally:
            monkeypatch.delenv("STT_BACKEND", raising=False)
            importlib.reload(stt)

    def test_공백만_있어도_기본값(self, monkeypatch):
        import importlib

        from app.agent import stt

        monkeypatch.setenv("STT_BACKEND", "   ")
        reloaded = importlib.reload(stt)
        try:
            assert reloaded.STT_BACKEND == "openai"
        finally:
            monkeypatch.delenv("STT_BACKEND", raising=False)
            importlib.reload(stt)


class TestSilenceGuard:
    """무음에 지어낸 조각을 버린다 (2026-09-16, ADR-0038 후속).

    whisper-1 은 무음·잡음에도 말을 지어낸다 — 유튜브 자막 문구가 지원자 답변으로
    저장된 사고가 있었다(2026-09-15). API 에는 로컬의 `vad_filter` 가 없어서
    `verbose_json` 의 `no_speech_prob` 로 거른다. **그 가드가 실시간 경로에만 있고
    백엔드(업로드 답변·재전사)에는 없었다.**
    """

    @staticmethod
    def _resp(segments, text="통째로 온 글"):
        r = MagicMock()
        r.text = text
        r.segments = segments
        r.duration = 3.0
        return r

    @staticmethod
    def _seg(text, prob):
        s = MagicMock()
        s.text = text
        s.no_speech_prob = prob
        return s

    def test_무음_조각은_버리고_말한_것만_남긴다(self):
        from app.agent import stt

        out = stt._text_without_silence(
            self._resp([
                self._seg(" 결제 정산 API 를 맡았습니다", 0.02),
                self._seg(" 다음 영상에서 만나요!", 0.95),
            ])
        )

        assert out == "결제 정산 API 를 맡았습니다"

    def test_전부_무음이면_빈_글이다(self):
        """빈 글은 「말이 안 담겼다」라 저장되지 않고 다시 답하게 된다 — 맞는 결과다."""
        from app.agent import stt

        assert stt._text_without_silence(
            self._resp([self._seg(" 시청해주셔서 감사합니다", 0.9)])
        ) == ""

    def test_조각_정보가_없으면_통째로_쓴다(self):
        """모델·형식이 바뀌어 조각이 안 와도 **답변을 잃지는 않는다** — 거르지 못할 뿐."""
        from app.agent import stt

        assert stt._text_without_silence(self._resp(None)) == "통째로 온 글"

    def test_로컬_전사도_vad_로_거른다(self):
        from app.agent import stt

        fake_seg = MagicMock()
        fake_seg.text = "안녕하세요"
        fake_info = MagicMock()
        fake_info.duration = 2.0
        fake_model = MagicMock()
        fake_model.transcribe.return_value = (iter([fake_seg]), fake_info)

        with patch.object(stt, "_get_local_model", return_value=fake_model):
            stt._transcribe_local(b"audio")

        kwargs = fake_model.transcribe.call_args.kwargs
        assert kwargs["vad_filter"] is True, "무음에 지어낸 말이 답변으로 저장된다"
        assert kwargs["condition_on_previous_text"] is False
