"""Optional per-report MedGemma backend adapted from Query_Design.

Imports are intentionally lazy so the standard-library regex/demo path remains
lightweight.  A server selecting this backend must provide a compatible
PyTorch/Transformers environment, GPU and Hugging Face credentials.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {
        "",
        "na",
        "n/a",
        "none",
        "null",
        "not mentioned",
        "not specified",
    }:
        return ""
    return text


def _chunks(text: str, chunk_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if chunk_chars <= overlap:
        raise ValueError("MedGemma chunk_chars must be larger than overlap")
    return [
        text[start : start + chunk_chars]
        for start in range(0, len(text), chunk_chars - overlap)
    ]


def _json_object(generated_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", generated_text, flags=re.IGNORECASE)
    for block in reversed(re.findall(r"\{[\s\S]*\}", cleaned)):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


class MedGemmaExtractor:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.model_id = self.config.get("model_id", "google/medgemma-1.5-4b-it")
        self.token_env = self.config.get("token_env", "HF_TOKEN")
        self.chunk_chars = int(self.config.get("chunk_chars", 6500))
        self.overlap = int(self.config.get("overlap", 700))
        self.max_input_tokens = int(self.config.get("max_input_tokens", 4096))
        self.max_new_tokens = int(self.config.get("max_new_tokens", 1200))
        self.load_in_4bit = bool(self.config.get("load_in_4bit", True))
        self.tokenizer: Any | None = None
        self.model: Any | None = None

    def _load(self) -> None:
        if self.model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(
                "MedGemma backend requires torch, transformers, accelerate and "
                "bitsandbytes in person A's server environment"
            ) from exc

        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError(f"MedGemma backend requires environment variable {self.token_env}")

        quantization = None
        if self.load_in_4bit:
            quantization = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=(
                    torch.bfloat16 if torch.cuda.is_available() else torch.float32
                ),
                bnb_4bit_use_double_quant=True,
            )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, token=token)
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            token=token,
            quantization_config=quantization,
            device_map="auto",
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        )
        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.model.eval()

    def _extract_chunk(self, chunk: str, items: list[str]) -> dict[str, str]:
        self._load()
        import torch

        keys = "\n".join(f'- "{item}"' for item in items)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a pathology information extractor. Use only the "
                    "provided report. Return only one valid JSON object. Use an "
                    "empty string when an item is not stated."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return JSON with exactly these keys:\n"
                    f"{keys}\n\nPathology report:\n\"\"\"{chunk}\"\"\""
                ),
            },
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        encoded = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_input_tokens,
        )
        input_ids = encoded["input_ids"].to(self.model.device)
        attention_mask = encoded.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(self.model.device)
        with torch.no_grad():
            output = self.model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        generated = self.tokenizer.decode(
            output[0][input_ids.shape[-1] :], skip_special_tokens=True
        )
        parsed = _json_object(generated)
        return {item: _clean(parsed.get(item)) for item in items}

    def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
        gross = re.search(
            r"\bGross\s*description\s*[:：]", report_text, flags=re.IGNORECASE
        )
        text = report_text[: gross.start()] if gross else report_text
        merged = {item: "" for item in items}
        for chunk in _chunks(text, self.chunk_chars, self.overlap):
            extracted = self._extract_chunk(chunk, items)
            for item in items:
                if not merged[item] and extracted[item]:
                    merged[item] = extracted[item]
        return {item: value for item, value in merged.items() if value}
