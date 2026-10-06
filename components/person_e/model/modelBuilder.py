"""Inference-only loader for the VLM used by the CLEE checkpoint.

The original project-wide builder also constructs pathology encoders, model
adapters, and several unrelated language models. Person E only
needs the MedGemma 1.5 base model and its processor, so this module keeps that
small, explicit surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch


SUPPORTED_MODEL = "medgemma-1.5-4b-it"


def log_print(message: Any) -> None:
    print(message, flush=True)


def move_to_device(value: Any, device: torch.device | str) -> Any:
    """Move tensors recursively without importing the old project utilities."""

    if torch.is_tensor(value):
        return value.to(device)
    if isinstance(value, dict):
        return {key: move_to_device(item, device) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(move_to_device(item, device) for item in value)
    if isinstance(value, list):
        return [move_to_device(item, device) for item in value]
    return value


class modelBuilder:
    """Build the frozen MedGemma backbone needed for CLEE forward passes."""

    def __init__(self, weight_path: str) -> None:
        self.weight_path = Path(weight_path).expanduser().resolve()

    def create_language_model(
        self,
        model_name: str,
        project_name: str | None = None,
        freeze_weight: bool = True,
        load_visual_processor: bool = False,
        torch_dtype: torch.dtype = torch.bfloat16,
        config_dict: dict[str, Any] | None = None,
        pp_num_gpus: int | None = None,
    ) -> tuple[Any, Any, Any, int, int, list[dict[str, Any]]]:
        if model_name != SUPPORTED_MODEL:
            raise ValueError(
                f"Person E supports only {SUPPORTED_MODEL!r}; got {model_name!r}"
            )
        if project_name != "CLEE":
            raise ValueError("The inference-only builder requires project_name='CLEE'")
        if not load_visual_processor:
            raise ValueError("CLEE image inference requires the visual processor")

        model_path = self.weight_path / model_name
        if not model_path.is_dir():
            raise FileNotFoundError(f"MedGemma model directory does not exist: {model_path}")

        from transformers import (
            AutoConfig,
            AutoProcessor,
            Gemma3ForConditionalGeneration,
        )

        options = dict(config_dict or {})
        config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
        bidirectional = options.get("use_bidirectional_attention")
        if bidirectional is not None:
            config.text_config.use_bidirectional_attention = bidirectional

        attention = options.get("attn_implementation") or "sdpa"
        device_map: str | dict[str, Any] | None = "auto"
        if pp_num_gpus is not None:
            if pp_num_gpus <= 0:
                raise ValueError("pp_num_gpus must be positive when supplied")
            if pp_num_gpus > torch.cuda.device_count():
                raise RuntimeError(
                    f"pp_num_gpus={pp_num_gpus} but only "
                    f"{torch.cuda.device_count()} CUDA devices are visible"
                )

        processor = AutoProcessor.from_pretrained(model_path)
        tokenizer = processor.tokenizer
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
            tokenizer.pad_token_id = tokenizer.eos_token_id

        wrapper = Gemma3ForConditionalGeneration.from_pretrained(
            model_path,
            config=config,
            dtype=torch_dtype,
            device_map=device_map,
            attn_implementation=attention,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        ).eval()
        model = wrapper.model
        # The CLEE path consumes the base model only.  Discarding the wrapper
        # releases lm_head while preserving the vision and text backbones.
        del wrapper
        if freeze_weight:
            model.requires_grad_(False)
        model.eval()

        text_config = model.config.text_config
        chat_template = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": None},
                    {"type": "text", "text": None},
                ],
            }
        ]
        return (
            model,
            processor,
            getattr(model, "generate", None),
            int(text_config.hidden_size),
            int(text_config.max_position_embeddings),
            chat_template,
        )
