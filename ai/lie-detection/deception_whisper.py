"""면접 음성 → 참/거짓 확률 (2026-09-14).

법정 영상 121개(Deceptive 61 / Truthful 60)로 fine-tuning한
Whisper-small 인코더를 HuggingFace 에서 받아 쓴다.
모델: cloverky/arda-deception-whisper  정확도 80%(테스트셋 25개).

**판정에 쓰지 않는다.** 결과는 담당자 화면 참고 지표로만 흐른다.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

HF_MODEL = "cloverky/arda-deception-whisper"
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2

_model = None
_failed = False


def _load():
    global _model, _failed
    if _failed:
        return None
    if _model is not None:
        return _model
    try:
        import torch
        import torch.nn as nn
        import whisper
        from huggingface_hub import hf_hub_download

        class WhisperClassifier(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = whisper.load_model("small").encoder
                self.classifier = nn.Sequential(
                    nn.AdaptiveAvgPool1d(1),
                    nn.Flatten(),
                    nn.Linear(768, 128),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(128, 2),
                )

            def forward(self, mel):
                x = self.encoder(mel)
                x = x.transpose(1, 2)
                return self.classifier(x)

        weights_path = hf_hub_download(repo_id=HF_MODEL, filename="pytorch_model.bin")
        m = WhisperClassifier()
        m.load_state_dict(torch.load(weights_path, map_location="cpu"))
        m.eval()
        _model = m
        logger.info("deception_whisper 모델 로드 완료 (%s)", HF_MODEL)
    except Exception:
        logger.warning("deception_whisper 모델 로드 실패 — 건너뛴다", exc_info=True)
        _failed = True
        return None
    return _model


def available() -> bool:
    return _load() is not None


def predict(pcm: bytes) -> dict | None:
    """16kHz PCM bytes → {"truth_pct": float, "lie_pct": float} 또는 None."""
    m = _load()
    if m is None:
        return None
    try:
        import torch
        import whisper

        usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
        audio = np.frombuffer(pcm[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio).unsqueeze(0)
        with torch.no_grad():
            logits = m(mel)
            probs = torch.softmax(logits, dim=1)[0].tolist()
        return {
            "truth_pct": round(probs[0] * 100, 1),
            "lie_pct": round(probs[1] * 100, 1),
        }
    except Exception:
        logger.exception("deception_whisper 추론 실패")
        return None
