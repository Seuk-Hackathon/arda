"""면접 영상 프레임 → 참/거짓 확률 (2026-09-14).

법정 영상 121개(Deceptive 61 / Truthful 60)로 fine-tuning한
ViT(google/vit-base-patch16-224) 를 HuggingFace 에서 받아 쓴다.
모델: cloverky/arda-deception-vit  정확도 89%(테스트셋 25개).

**판정에 쓰지 않는다.** 결과는 담당자 화면 참고 지표로만 흐른다 —
표정·음성 신호와 달리 신뢰 구간이 넓어 판정(verdict)에 섞을 수 없다.
"""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

HF_MODEL = "cloverky/arda-deception-vit"

_model = None
_processor = None
_failed = False


def _load():
    global _model, _processor, _failed
    if _failed:
        return None, None
    if _model is not None:
        return _model, _processor
    try:
        from transformers import ViTForImageClassification, ViTImageProcessor

        _processor = ViTImageProcessor.from_pretrained(HF_MODEL)
        _model = ViTForImageClassification.from_pretrained(HF_MODEL)
        _model.eval()
        logger.info("deception_vit 모델 로드 완료 (%s)", HF_MODEL)
    except Exception:
        logger.warning("deception_vit 모델 로드 실패 — 건너뛴다", exc_info=True)
        _failed = True
        return None, None
    return _model, _processor


def available() -> bool:
    m, _ = _load()
    return m is not None


def predict(bgr: "np.ndarray") -> dict | None:
    """BGR 프레임 → {"truth_pct": float, "lie_pct": float} 또는 None."""
    m, proc = _load()
    if m is None:
        return None
    try:
        import torch
        from PIL import Image

        rgb = bgr[:, :, ::-1]
        img = Image.fromarray(rgb.astype(np.uint8))
        inputs = proc(images=img, return_tensors="pt")
        with torch.no_grad():
            logits = m(**inputs).logits
            probs = torch.softmax(logits, dim=1)[0].tolist()
        # 학습 시 label 0=진실, 1=거짓
        return {
            "truth_pct": round(probs[0] * 100, 1),
            "lie_pct": round(probs[1] * 100, 1),
        }
    except Exception:
        logger.exception("deception_vit 추론 실패")
        return None
