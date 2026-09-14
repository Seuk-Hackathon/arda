"""Qwen3-8B QLoRA 학습 (RTX 4060 8GB / T4 16GB).

- 4-bit nf4 + double quant · bfloat16 compute
- LoRA r=16 · attention + MLP projection 전부
- gradient checkpointing · batch 1 · grad accum 8 (실효 8)
- max_seq_length=4096 (T4) / 2048 (4060)
- **손실은 assistant 응답 구간에만** — 수동 마스킹 (`labels=-100` 나머지 전부)

산출물: output/checkpoint-*/adapter_model.safetensors
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# CUDA 파편화 완화 — T4 16GB 에서 큰 activation 연속 블록 할당 실패를 줄인다
# (에러 메시지가 안내한 튜닝). torch import **이전에** 설정해야 유효.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from datasets import Dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
)
from trl import SFTConfig, SFTTrainer

ROOT = Path(__file__).parent
# ADR-0032 는 ollama `qwen3:8b` (Q4) 로 표기 · HF 상 대응은 `Qwen/Qwen3-8B` (Instruct 접미어 없음)
MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen3-8B")
OUTPUT_DIR = ROOT / "output"
# T4 16GB · 실측 4096 OOM (v3) · 2048 도 OOM (v4). 1024 로 내림. 시스템 프롬프트가
# 잘리는 부분이 커지지만 assistant 응답은 살아 있다 (`truncation_side="left"`).
# 실측: 09-11 판 4096 성공 → 그때는 trl 이 다른 경로였을 것. 지금 SFTTrainer 는
# `DataCollatorForSeq2Seq` 로 패딩하고 pre-tokenized 데이터를 쓰는 조합이라 메모리
# 프로파일이 다르다. 1024 에서 여유 확인 후 필요하면 1536 시도.
MAX_SEQ_LENGTH = int(os.getenv("MAX_SEQ_LENGTH", "1024"))
NUM_EPOCHS = int(os.getenv("NUM_EPOCHS", "3"))
LEARNING_RATE = float(os.getenv("LEARNING_RATE", "2e-4"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))
GRAD_ACCUM = int(os.getenv("GRAD_ACCUM", "8"))

# assistant 표식 (Qwen3 chat_template · v1.md 확인). 이 두 마커 사이의 토큰만 학습 대상.
ASSISTANT_HEADER = "<|im_start|>assistant\n"
TURN_END = "<|im_end|>"


def _render_assistant(content: Any) -> str:
    """assistant content(list[dict]) → 학습 대상 문자열.

    Qwen3 는 tool_call 을 `<tool_call>{"name":...,"arguments":...}</tool_call>` XML 로
    다룬다. 우리는 build_dataset.py 가 만든 list-of-blocks 구조를 그 형식으로 렌더링한다.
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            payload = json.dumps(
                {"name": block["name"], "arguments": block.get("input", {})},
                ensure_ascii=False,
            )
            parts.append(f"<tool_call>\n{payload}\n</tool_call>")
    return "\n".join(p for p in parts if p)


def _messages_as_strings(sample: dict[str, Any]) -> list[dict[str, str]]:
    """{messages: [{role, content(list|str)}]} → messages with string content."""
    out = []
    for m in sample["messages"]:
        content = _render_assistant(m["content"]) if m["role"] == "assistant" else m["content"]
        out.append({"role": m["role"], "content": content})
    return out


def _assistant_char_spans(text: str) -> list[tuple[int, int]]:
    """chat_template 이 렌더한 `text` 에서 assistant 응답 문자 구간을 찾는다.

    구간은 `<|im_start|>assistant\\n` 뒤부터 그 뒤 첫 `<|im_end|>` 를 **포함** 하는 위치까지.
    `<|im_end|>` 자체도 학습 대상에 포함시켜 모델이 응답 종료를 배우게 한다.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    while True:
        s = text.find(ASSISTANT_HEADER, i)
        if s == -1:
            break
        content_start = s + len(ASSISTANT_HEADER)
        e = text.find(TURN_END, content_start)
        if e == -1:
            content_end = len(text)
        else:
            content_end = e + len(TURN_END)
        spans.append((content_start, content_end))
        i = content_end
    return spans


def tokenize_with_assistant_mask(sample: dict[str, Any], tokenizer, max_length: int) -> dict[str, list[int]]:
    """샘플 하나 → input_ids · attention_mask · labels (assistant 밖은 -100).

    Qwen3 chat_template 에 `{% generation %}` 마커가 없어 `trl` 의 자동 assistant_only_loss
    가 작동하지 않는다 (실측 · trl 0.29 는 RuntimeError). 대신 문자 오프셋으로 assistant
    구간을 직접 찾아 그 밖의 토큰을 -100 으로 가려 손실 계산에서 제외한다.

    **이 함수가 이번 재학습의 핵심** — 이전 09-11 판에서 손실이 전체 시퀀스에
    걸려 시스템 프롬프트를 외운 것이 원인이었다 (`eval_loss` 0.34→0.07 는 프롬프트
    암기의 결과). 여기서 assistant 응답만 학습 대상이 되도록 라벨을 만든다.
    """
    text = tokenizer.apply_chat_template(
        _messages_as_strings(sample),
        tokenize=False,
        add_generation_prompt=False,
    )
    spans = _assistant_char_spans(text)

    enc = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        return_offsets_mapping=True,
        add_special_tokens=False,  # chat_template 이 이미 특수 토큰 삽입
    )
    input_ids = enc["input_ids"]
    attention_mask = enc["attention_mask"]
    offsets = enc["offset_mapping"]

    labels = []
    for tok_id, (start, end) in zip(input_ids, offsets):
        if end == 0:  # padding/특수 오프셋
            labels.append(-100)
            continue
        # 토큰의 문자 구간이 어떤 assistant span 안에 (한쪽만이라도) 걸리면 학습 대상
        keep = any(start >= a_start and end <= a_end for a_start, a_end in spans)
        labels.append(tok_id if keep else -100)

    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    if not torch.cuda.is_available():
        print("[train] CUDA 없음 — 4060 을 못 본다. 드라이버·pytorch 빌드 확인.", file=sys.stderr)
        return 1
    print(f"[train] GPU: {torch.cuda.get_device_name(0)} · VRAM {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB", file=sys.stderr)

    train_path = ROOT / "dataset.train.jsonl"
    val_path = ROOT / "dataset.val.jsonl"
    if not train_path.exists():
        print("[train] dataset 없음 — build_dataset.py 먼저", file=sys.stderr)
        return 1

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    print(f"[train] 모델 로드: {MODEL_ID}", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    # 왼쪽 자르기 — 시스템 프롬프트(~3000 토큰)가 max_length(2048) 를 넘길 때
    # 앞 부분을 자른다. 뒷쪽에 assistant 응답이 있으므로 살려야 한다. 오른쪽 자르기
    # (기본) 로 두면 assistant 가 통째로 사라져 labels=-100 뿐이라 학습이 안 된다.
    tokenizer.truncation_side = "left"

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_cfg,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model)

    # trl 1.13 SFTTrainer 는 peft_config 를 받아 자기 안에서 LoRA 를 씌우므로
    # 여기선 정의만 하고 넘긴다 · get_peft_model 을 미리 부르지 않는다.
    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    train_raw = load_jsonl(train_path)
    val_raw = load_jsonl(val_path) if val_path.exists() else []
    print(f"[train] train={len(train_raw)} val={len(val_raw)}", file=sys.stderr)

    # 각 샘플을 미리 토큰화 + 라벨링 (assistant 밖 -100). 학습 중 매번 하지 않는다.
    train_tok = [tokenize_with_assistant_mask(s, tokenizer, MAX_SEQ_LENGTH) for s in train_raw]
    val_tok = [tokenize_with_assistant_mask(s, tokenizer, MAX_SEQ_LENGTH) for s in val_raw] if val_raw else []

    # 실측 로그 — 학습 대상 토큰 비율이 어떻게 나오는지 (이전 판은 1.8% 였다).
    total_tok = sum(len(s["input_ids"]) for s in train_tok)
    labeled_tok = sum(sum(1 for l in s["labels"] if l != -100) for s in train_tok)
    print(
        f"[train] 학습 토큰 비율: {labeled_tok}/{total_tok} = {labeled_tok/total_tok:.1%}",
        file=sys.stderr,
    )

    train_ds = Dataset.from_list(train_tok)
    val_ds = Dataset.from_list(val_tok) if val_tok else None

    args = SFTConfig(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=LEARNING_RATE,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        bf16=True,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if val_ds else "no",
        optim="paged_adamw_8bit",
        report_to="none",
        max_length=MAX_SEQ_LENGTH,
        packing=False,
        # 데이터를 이미 토큰화·라벨링해서 넘긴다 — trainer 안에서 다시 처리하지 않게.
        dataset_kwargs={"skip_prepare_dataset": True},
    )

    # 패딩만 하는 콜레이터. labels 는 이미 우리가 만들어 둔 것.
    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )

    trainer = SFTTrainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tokenizer,
        peft_config=lora_cfg,
        data_collator=collator,
    )

    print("[train] 학습 시작", file=sys.stderr)
    trainer.train()
    trainer.save_model(str(OUTPUT_DIR / "final"))
    tokenizer.save_pretrained(str(OUTPUT_DIR / "final"))
    print(f"[train] 완료 → {OUTPUT_DIR / 'final'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
