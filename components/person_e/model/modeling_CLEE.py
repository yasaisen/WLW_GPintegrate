"""
 SPDX-License-Identifier: MIT
 Copyright (c) 2026, yasaisen (clover)
 
 This file is part of a project licensed under the MIT License.
 See the LICENSE file in the project root for more information.
 
 last modified in 2604301357
"""


import torch
import torch.nn as nn
from typing import Any, List, Dict, Tuple, Optional
from transformers import AddedToken


from .contracts import Case
from .modelBuilder import log_print, modelBuilder, move_to_device


SYSTEM_PROMPT = ""

DEEP_PREFIX_CONFIG = {
    "pre_trans_prefix": "use_pre_trans_prefix",
    "post_trans_prefix": "use_post_trans_prefix",
    "pre_attn_prefix": "use_pre_attn_prefix",
    "pre_mlp_prefix": "use_pre_mlp_prefix",
    "pre_ple_prefix": "use_pre_ple_prefix",
}

DEEP_PREFIX_KEYS = tuple(DEEP_PREFIX_CONFIG.keys())


class SharedLearnablePrefix(nn.Module):
    def __init__(self, 
        prefix_len: int, 
        hidden_dim: int, 
        dtype=torch.float32
    ):
        super().__init__()
        self.weight = nn.Parameter(
            torch.randn(prefix_len, hidden_dim, dtype=dtype) * 0.02
        )

    def get(self
    ) -> torch.Tensor:
        return self.weight


class LayerwiseSharedLearnablePrefix(nn.Module):
    def __init__(self,
        num_layers: int,
        prefix_len: int,
        hidden_dim: int,
        dtype=torch.float32
    ):
        super().__init__()
        self.weight = nn.Parameter(
            torch.randn(num_layers, prefix_len, hidden_dim, dtype=dtype) * 0.02
        )

    def get(self,
        layer_idx: int,
    ) -> torch.Tensor:
        return self.weight[layer_idx]


class CaseLevelEvidenceEvaluator(nn.Module):
    def __init__(self, 
        system_prompt_path: str = None,
        temperature: float = 1.0,
        input_img: bool = True,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        super().__init__()
        # self.temperature = temperature
        self.device = torch.device(device)
        self.input_img = bool(input_img)
        # if system_prompt_path is not None:
        #     with open(system_prompt_path, "r") as file:
        #         self.system_prompt = file.read()
        # else:
        #     self.system_prompt = SYSTEM_PROMPT

        self.deep_prefix_debug_log = True
        self.deep_prefix_debug_log_freq = 50
        self._deep_prefix_debug_counter = 0

    def init_vlm_model(self, 
        vlm_processor, 
        vlm_model,
        max_senLen: int, 
    ):
        self.vlm_processor = vlm_processor
        if not hasattr(self.vlm_processor, "tokenizer"):
            raise ValueError("vlm_processor must have a 'tokenizer' attribute.")

        vlm_model = vlm_model.eval()
        for p in vlm_model.parameters():
            p.requires_grad_(False)

        object.__setattr__(self, "vlm_model", vlm_model)
        object.__setattr__(self, "text_backbone", self._resolve_text_backbone(vlm_model))
        self.text_backbone.eval()

        log_print(
            "vlm_model.config.text_config.use_bidirectional_attention = "
            f"{getattr(vlm_model.config.text_config, 'use_bidirectional_attention', None)}"
        )
        self.model_type = vlm_model.config.model_type
        self.model_dtype = vlm_model.dtype
        self.hidden_size = vlm_model.config.text_config.hidden_size
        self.num_text_layers = self._get_num_text_layers()

        self.img_tok_id = getattr(self.vlm_model.config, "boi_token_id", None)
        if self.img_tok_id is None:
            self.img_tok_id = self.vlm_processor.tokenizer.convert_tokens_to_ids("<start_of_image>")
            log_print(f"Using tokenizer to get ID for '<start_of_image>': {self.img_tok_id}")
        else:
            log_print(f"Using model config's boi_token_id for image token: {self.img_tok_id}") # NOTE: offen here.

    def _resolve_text_backbone(self, 
        root: nn.Module
    ) -> nn.Module:
        queue = [root]
        visited = set()

        while queue:
            module = queue.pop(0)
            mid = id(module)
            if mid in visited:
                continue
            visited.add(mid)

            layers = getattr(module, "layers", None)
            if layers is not None:
                try:
                    if len(layers) > 0 and isinstance(layers[0], nn.Module):
                        return module
                except Exception:
                    pass

            for name in ("language_model",): # , "model", "text_model", "transformer"):
                child = getattr(module, name, None)
                if isinstance(child, nn.Module):
                    queue.append(child)

        raise RuntimeError("Unable to parse text backbone from the current model structure (missing .layers).")

    def _get_num_text_layers(self, 
    ) -> int:
        layers = getattr(self.text_backbone, "layers", None)
        if layers is None:
            raise RuntimeError("text_backbone has no .layers, unable to initialize deep prefix modules.")
        num_layers = len(layers)
        if num_layers <= 0:
            raise RuntimeError("text_backbone.layers is empty, unable to initialize deep prefix modules.")
        return int(num_layers)




    def init_prefix(self, 
        DxItem_list: List[str],
        active_DxItem_list: Optional[List[str]] = None,
        declared_DxResult_dict: Optional[Dict[str, List[str]]] = None,
        active_DxResult_dict: Optional[Dict[str, List[str]]] = None,
        prefix_len: int = 1, 
        use_pre_trans_prefix: bool = True,
        use_post_trans_prefix: bool = False,
        use_pre_attn_prefix: bool = False,
        use_pre_mlp_prefix: bool = False,
        use_pre_ple_prefix: bool = False,
    ):
        self.declared_DxItem_list = list(DxItem_list)
        self.DxItem_list = list(self.declared_DxItem_list)
        if len(self.DxItem_list) == 0:
            raise ValueError("DxItem_list is empty, unable to initialize prefix modules.")
        self.active_DxItem_list = list(
            self.declared_DxItem_list
            if active_DxItem_list is None
            else active_DxItem_list
        )
        undeclared_active_DxItems = [
            DxItem
            for DxItem in self.active_DxItem_list
            if DxItem not in self.declared_DxItem_list
        ]
        if undeclared_active_DxItems:
            raise ValueError(
                "active_DxItem_list contains undeclared DxItems: "
                + ", ".join(undeclared_active_DxItems)
            )
        self.active_DxItem_set = set(self.active_DxItem_list)
        self.declared_DxResult_dict = {
            DxItem: list(DxResults)
            for DxItem, DxResults in (
                declared_DxResult_dict or {}
            ).items()
        }
        self.active_DxResult_dict = {
            DxItem: list(DxResults)
            for DxItem, DxResults in (
                active_DxResult_dict or {}
            ).items()
        }

        self.prefix_len = int(prefix_len)
        if self.prefix_len <= 0:
            raise ValueError(f"prefix_len must be > 0, but got {self.prefix_len}.")

        log_print(f"layer num for deep prefix injection: {self.num_text_layers}")

        self.deep_prefix_use_flags = {
            "pre_trans_prefix": bool(use_pre_trans_prefix),
            "post_trans_prefix": bool(use_post_trans_prefix),
            "pre_attn_prefix": bool(use_pre_attn_prefix),
            "pre_mlp_prefix": bool(use_pre_mlp_prefix),
            "pre_ple_prefix": bool(use_pre_ple_prefix),
        }
        self.active_deep_prefix_keys = [
            prefix_key for prefix_key in DEEP_PREFIX_KEYS if self.deep_prefix_use_flags[prefix_key]
        ]
        if len(self.active_deep_prefix_keys) == 0:
            log_print("[DeepPrefix] No layer-wise deep prefix position is enabled.")
        else:
            log_print(f"[DeepPrefix] enabled positions: {', '.join(self.active_deep_prefix_keys)}")

        shallow_prefix = {}
        deep_prefix_by_key = {prefix_key: {} for prefix_key in self.active_deep_prefix_keys}
        for DxItem in self.DxItem_list:
            if not isinstance(DxItem, str) or len(DxItem.strip()) == 0:
                raise ValueError(f"Invalid DxItem key for prefix: {DxItem!r}")
            if "." in DxItem:
                raise ValueError(f"DxItem '{DxItem}' contains '.', which is unsupported for nn.ModuleDict keys.")
            if DxItem in shallow_prefix:
                raise ValueError(f"Duplicate DxItem '{DxItem}' detected when building prefix.")

            shallow_prefix[DxItem] = SharedLearnablePrefix(
                prefix_len=self.prefix_len, 
                hidden_dim=self.hidden_size, 
                dtype=torch.float32, 
            )
            for prefix_key in self.active_deep_prefix_keys:
                deep_prefix_by_key[prefix_key][DxItem] = LayerwiseSharedLearnablePrefix(
                    num_layers=self.num_text_layers, 
                    prefix_len=self.prefix_len, 
                    hidden_dim=self.hidden_size, 
                    dtype=torch.float32, 
                )

        prefix_modules = {"shallow_prefix": nn.ModuleDict(shallow_prefix).to(self.device)}
        for prefix_key in self.active_deep_prefix_keys:
            prefix_modules[prefix_key] = nn.ModuleDict(deep_prefix_by_key[prefix_key]).to(self.device)

        self.prefix_module_dict = nn.ModuleDict(prefix_modules).to(self.device)



    def load_shared_prefix(self, 
        path: str,
        strict: bool = True,
        map_location: Optional[str] = None,
    ) -> Tuple[List[str], List[str]]:
        load_device = self.device if map_location is None else map_location

        payload = torch.load(path, map_location=load_device, weights_only=True)
        required_keys = ["DxItem_list", "prefix_len", "num_text_layers", "prefix_module_dict_state_dict"]
        if any(k not in payload for k in required_keys):
            raise RuntimeError(f"Prefix checkpoint at {path} is missing required keys. Expected keys: {required_keys}. Found keys: {list(payload.keys())}.")

        saved_DxItem_list = payload["DxItem_list"]
        saved_prefix_len = int(payload["prefix_len"])
        saved_num_text_layers = int(payload["num_text_layers"])
        saved_deep_prefix_use_flags = payload.get("deep_prefix_use_flags", None)
        saved_active_DxItem_list = payload.get("active_DxItem_list", None)
        saved_active_DxResult_dict = payload.get(
            "active_DxResult_dict",
            None,
        )

        current_DxItem_list = list(self.DxItem_list)
        current_prefix_len = int(self.prefix_len)
        current_num_text_layers = int(self.num_text_layers)
        current_deep_prefix_use_flags = dict(getattr(self, "deep_prefix_use_flags", {}))

        if (
            current_DxItem_list != list(saved_DxItem_list) or 
            current_prefix_len != saved_prefix_len or 
            current_num_text_layers != saved_num_text_layers
        ):
            raise RuntimeError(f"Prefix checkpoint structure mismatch. Saved DxItem_list: {saved_DxItem_list}, prefix_len: {saved_prefix_len}, num_text_layers: {saved_num_text_layers}. Current model DxItem_list: {current_DxItem_list}, prefix_len: {current_prefix_len}, num_text_layers: {current_num_text_layers}.")
        if saved_deep_prefix_use_flags is not None and current_deep_prefix_use_flags != dict(saved_deep_prefix_use_flags):
            raise RuntimeError(
                f"Deep prefix position flags mismatch. Saved: {saved_deep_prefix_use_flags}. "
                f"Current: {current_deep_prefix_use_flags}."
            )
        if (
            saved_active_DxItem_list is not None
            and list(self.active_DxItem_list) != list(saved_active_DxItem_list)
        ):
            raise RuntimeError(
                "Active DxItem space mismatch. "
                f"Saved: {saved_active_DxItem_list}; "
                f"current: {self.active_DxItem_list}."
            )
        if (
            saved_active_DxResult_dict is not None
            and dict(self.active_DxResult_dict)
            != dict(saved_active_DxResult_dict)
        ):
            raise RuntimeError(
                "Active DxResult space mismatch. "
                f"Saved: {saved_active_DxResult_dict}; "
                f"current: {self.active_DxResult_dict}."
            )

        try:
            msg = self.prefix_module_dict.load_state_dict(
                payload["prefix_module_dict_state_dict"], 
                strict=strict, 
            )
        except RuntimeError as e:
            raise RuntimeError(f"Prefix state_dict mismatch when loading checkpoint from {path}. {e}")

        log_print("\033[92m Successfully Loaded Pretrained model from {} \033[00m".format(path))
        return list(msg.missing_keys), list(msg.unexpected_keys)





    def init_sep(self, 
        sep_str: str = "<unused0>",
        boc_str: str = "<unused1>",
    ):
        self.sep_str = sep_str
        sep_token = AddedToken(self.sep_str, normalized=False, special=True)
        self.vlm_processor.tokenizer.add_special_tokens({'additional_special_tokens': [sep_token]})

        self.sep_tok_id = self.vlm_processor.tokenizer.convert_tokens_to_ids(self.sep_str)
        assert self.sep_tok_id != self.vlm_processor.tokenizer.unk_token_id, f"{self.sep_str} is not in the vocabulary. Please use another unused token."
        log_print(f"[SEP] token: '{self.sep_str}' -> id={self.sep_tok_id}")

        self.boc_str = boc_str
        boc_token = AddedToken(self.boc_str, normalized=False, special=True)
        self.vlm_processor.tokenizer.add_special_tokens({'additional_special_tokens': [boc_token]})

        self.boc_tok_id = self.vlm_processor.tokenizer.convert_tokens_to_ids(self.boc_str)
        assert self.boc_tok_id != self.vlm_processor.tokenizer.unk_token_id, f"{self.boc_str} is not in the vocabulary. Please use another unused token."
        log_print(f"[BOC] token: '{self.boc_str}' -> id={self.boc_tok_id}")



    def build_inputs(self, 
        case: Case, 
    ):
        messages = self._build_messages(
            case=case
        )

        if self.model_type in ["gemma4"]:
            text_prompt = self.vlm_processor.apply_chat_template(
                messages, 
                tokenize=False, 
                add_generation_prompt=True, 
                enable_thinking=False, 
            )
        else:
            text_prompt = self.vlm_processor.apply_chat_template(
                messages, 
                tokenize=False, 
                add_generation_prompt=True, 
            )
        raw_inputs = self.vlm_processor( 
            text=text_prompt, 
            images=(
                [roi.image for roi in case.rois]
                if self.input_img
                else None
            ), 
            return_tensors="pt", 
        )
        inputs = {}
        for k, v in raw_inputs.items():
            if torch.is_tensor(v):
                v = v.to(self.device)
                if torch.is_floating_point(v):
                    v = v.to(self.model_dtype)
            inputs[k] = v

        roi_DxItems = [roi.DxItem for roi in case.rois]
        for DxItem in roi_DxItems:
            if DxItem not in self.DxItem_list:
                raise ValueError(f"DxItem '{DxItem}' not found in case_id {case.case_id}.")
            if DxItem not in self.active_DxItem_set:
                raise ValueError(
                    f"DxItem '{DxItem}' is declared but inactive in "
                    f"case_id {case.case_id}."
                )

        return inputs, roi_DxItems

    def _build_messages(self, 
        case: Case
    ) -> Dict:
        content = []
        for roi in case.rois:
            if self.input_img and roi.image is None:
                raise ValueError(
                    f"input_img=True but ROI {roi.global_idx} in "
                    f"case_id {case.case_id} has no image."
                )
            if not self.input_img and roi.image is not None:
                raise ValueError(
                    f"input_img=False but ROI {roi.global_idx} in "
                    f"case_id {case.case_id} contains an image."
                )
            if roi.image is None and roi.cxcywh is None and roi.mpp is None and roi.visualAttrs is None:
                raise ValueError(f"ROI in case_id {case.case_id} has no content (image, cxcywh, mpp, visualAttrs all None).")

            if self.input_img:
                content += [
                    {
                        "type": "image", 
                    }
                ]

            text = ""
            if not self.input_img:
                text += self.boc_str 
            if roi.mpp is not None:
                text += f"MPP: {float(roi.mpp):.6f}, "
            if roi.cxcywh is not None:
                cx, cy, width, height = roi.cxcywh
                text += (
                    f"cxcywh: ({float(cx):.6f}, {float(cy):.6f}, "
                    f"{float(width):.6f}, {float(height):.6f}), "
                )
            if roi.visualAttrs is not None:
                text += f"visualAttrs: {roi.visualAttrs}, "

            text += self.sep_str
            content += [
                {
                    "type": "text",
                    "text": text
                }
            ]
        messages = [
            {
                "role": "user", 
                "content": content
            },
        ]
        return messages



    def get_merged_embeds(self, 
        inputs: dict, 
    ) -> Any:
        captured = {}

        def hook(module, args, kwargs):
            x = args[0] if args else kwargs.get("hidden_states")
            if x is not None:
                captured["embeds"] = x.detach().clone()

        def text_backbone_hook(module, args, kwargs):
            per_layer_inputs = kwargs.get("per_layer_inputs")
            if per_layer_inputs is not None:
                captured["per_layer_inputs"] = per_layer_inputs.detach().clone()

        first_text_layer = self.text_backbone.layers[0]
        handle = first_text_layer.register_forward_pre_hook(hook, with_kwargs=True)
        text_backbone_handle = self.text_backbone.register_forward_pre_hook(text_backbone_hook, with_kwargs=True)
        try:
            with torch.no_grad():
                self.vlm_model(**inputs, output_hidden_states=False, use_cache=False)
        finally:
            handle.remove()
            text_backbone_handle.remove()

        if "embeds" not in captured:
            raise RuntimeError("No merged embeddings were found. Please check the model structure or hook attachment points.")

        merged_embeds = captured["embeds"].to(
            device=self.device,
            dtype=self.model_dtype 
        )

        per_layer_inputs = captured.get("per_layer_inputs", None)
        if per_layer_inputs is not None:
            per_layer_inputs = per_layer_inputs.to(
                device=self.device,
                dtype=self.model_dtype,
            )

        return merged_embeds, per_layer_inputs



    def _find_insert_positions(self, 
        input_ids: torch.Tensor
    ) -> List[int]:

        if self.input_img:
            positions = (input_ids[0] == self.img_tok_id).nonzero(as_tuple=True)[0].tolist()
        else:
            positions = (input_ids[0] == self.boc_tok_id).nonzero(as_tuple=True)[0].tolist()
        if not positions:
            marker_name = "BOI" if self.input_img else "BOC"
            raise RuntimeError(
                f"No {marker_name} token found, unable to locate ROI starts."
            )
        
        return positions

    def insert_prefix_embeds(self, 
        input_ids: torch.Tensor, 
        merged_embeds: torch.Tensor, 
        roi_DxItems: List[str],
        per_layer_inputs: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, List[int], Optional[torch.Tensor]]:
        shallow_prefix = self.prefix_module_dict["shallow_prefix"]
        insert_positions = self._find_insert_positions(input_ids)
        if len(insert_positions) != len(roi_DxItems):
            raise ValueError(f"ROI count mismatch: len(insert_positions)={len(insert_positions)} vs len(roi_DxItems)={len(roi_DxItems)}.")
        if any(DxItem not in shallow_prefix for DxItem in roi_DxItems):
            raise ValueError(f"shared_prefix for some ROI is not initialized.")
        if per_layer_inputs is not None and per_layer_inputs.shape[:2] != merged_embeds.shape[:2]:
            raise ValueError(f"per_layer_inputs batch/seq mismatch: per_layer_inputs.shape[:2]={tuple(per_layer_inputs.shape[:2])}, merged_embeds.shape[:2]={tuple(merged_embeds.shape[:2])}.")

        segments = []
        per_layer_segments = [] if per_layer_inputs is not None else None
        prefix_per_layer_inputs = self._build_pad_per_layer_inputs(
            prefix_len=self.prefix_len, 
            reference=per_layer_inputs, 
        )
        if per_layer_inputs is not None and prefix_per_layer_inputs is None:
            raise RuntimeError("per_layer_inputs were provided, but prefix per-layer inputs could not be built.")
        
        prefix_positions = []
        prev = 0
        offset = 0
        for roi_idx, insert_pos in enumerate(insert_positions):
            if insert_pos > prev:
                segments.append(merged_embeds[:, prev:insert_pos, :])
                if per_layer_segments is not None:
                    per_layer_segments.append(per_layer_inputs[:, prev:insert_pos, :, :])
                offset += insert_pos - prev

            DxItem = roi_DxItems[roi_idx]

            prefix_w = shallow_prefix[DxItem].get()
            if prefix_w.ndim != 2:
                raise ValueError(f"shared_prefix['{DxItem}'] must be 2D (P, H), got shape={tuple(prefix_w.shape)}.")
            if prefix_w.shape[0] != self.prefix_len:
                raise ValueError(
                    f"shared_prefix['{DxItem}'] prefix_len mismatch: expected {self.prefix_len}, got {prefix_w.shape[0]}."
                )
            if prefix_w.shape[1] != merged_embeds.shape[-1]:
                raise ValueError(
                    f"shared_prefix['{DxItem}'] hidden_dim mismatch: expected {merged_embeds.shape[-1]}, got {prefix_w.shape[1]}."
                )
            
            prefix_seg = prefix_w.to(
                device=merged_embeds.device,
                dtype=merged_embeds.dtype,
            ).unsqueeze(0).expand(1, -1, -1).clone()
            prefix_positions.append(offset)
            segments.append(prefix_seg)
            if per_layer_segments is not None:
                per_layer_segments.append(
                    prefix_per_layer_inputs.expand(per_layer_inputs.shape[0], -1, -1, -1).clone()
                )
            offset += self.prefix_len

            prev = insert_pos


        if prev < merged_embeds.shape[1]:
            segments.append(merged_embeds[:, prev:, :])
            if per_layer_segments is not None:
                per_layer_segments.append(per_layer_inputs[:, prev:, :, :])

        new_embeds = torch.cat(segments, dim=1)
        new_per_layer_inputs = torch.cat(per_layer_segments, dim=1) if per_layer_segments is not None else None


        total_len = new_embeds.shape[1]
        attention_mask = torch.ones(1, total_len, dtype=torch.long, device=self.device)

        return new_embeds, attention_mask, prefix_positions, new_per_layer_inputs

    def _build_pad_per_layer_inputs(self,
        prefix_len: int,
        reference: Optional[torch.Tensor],
    ) -> Optional[torch.Tensor]:
        if reference is None:
            return None
        if not hasattr(self.text_backbone, "get_per_layer_inputs"):
            return None

        text_config = getattr(self.text_backbone, "config", None)
        pad_token_id = getattr(text_config, "pad_token_id", None)
        if pad_token_id is None:
            pad_token_id = getattr(self.vlm_processor.tokenizer, "pad_token_id", None)
        if pad_token_id is None:
            raise RuntimeError("Unable to build Gemma4 per-layer inputs: pad_token_id is missing.")

        embed_module = getattr(self.text_backbone, "embed_tokens_per_layer", None)
        embed_weight = getattr(embed_module, "weight", None)
        input_device = embed_weight.device if embed_weight is not None else reference.device
        pad_ids = torch.full(
            (1, prefix_len), 
            int(pad_token_id), 
            dtype=torch.long, 
            device=input_device, 
        )

        with torch.no_grad():
            pad_per_layer_inputs = self.text_backbone.get_per_layer_inputs(pad_ids, None)

        return pad_per_layer_inputs.to(
            device=reference.device, 
            dtype=reference.dtype, 
        )



    def _register_deep_prefix_hooks(self, 
        prefix_positions: List[int],
        roi_DxItems: List[str],
    ):
        handles = []
        layers = getattr(self.text_backbone, "layers", None)
        if layers is None:
            raise RuntimeError("text_backbone has no .layers, unable to register deep prefix hooks.")

        active_prefix_keys = self._get_active_deep_prefix_keys()
        if len(active_prefix_keys) == 0:
            return handles

        for layer_idx, layer in enumerate(layers):
            if "pre_trans_prefix" in active_prefix_keys:
                handles.append(
                    layer.register_forward_pre_hook(
                        self._make_deep_prefix_pre_hook(
                            prefix_key="pre_trans_prefix",
                            layer_idx=layer_idx,
                            prefix_positions=prefix_positions,
                            roi_DxItems=roi_DxItems,
                            hook_name="decoder layer pre-hook",
                        ),
                        with_kwargs=True,
                    )
                )

            if "post_trans_prefix" in active_prefix_keys:
                handles.append(
                    layer.register_forward_hook(
                        self._make_deep_prefix_post_hook(
                            prefix_key="post_trans_prefix",
                            layer_idx=layer_idx,
                            prefix_positions=prefix_positions,
                            roi_DxItems=roi_DxItems,
                        ),
                        with_kwargs=True,
                    )
                )

            if "pre_attn_prefix" in active_prefix_keys:
                input_layernorm = getattr(layer, "input_layernorm", None)
                if not isinstance(input_layernorm, nn.Module):
                    raise RuntimeError(f"text_backbone.layers[{layer_idx}] has no nn.Module input_layernorm for pre_attn_prefix hook.")  # 結構不符時直接中止。
                handles.append(
                    input_layernorm.register_forward_pre_hook(
                        self._make_deep_prefix_pre_hook(
                            prefix_key="pre_attn_prefix",
                            layer_idx=layer_idx,
                            prefix_positions=prefix_positions,
                            roi_DxItems=roi_DxItems,
                            hook_name="input_layernorm pre-hook",
                        ),
                        with_kwargs=True,
                    )
                )

            if "pre_mlp_prefix" in active_prefix_keys:
                pre_feedforward_layernorm = getattr(layer, "pre_feedforward_layernorm", None)
                if not isinstance(pre_feedforward_layernorm, nn.Module):
                    raise RuntimeError(f"text_backbone.layers[{layer_idx}] has no nn.Module pre_feedforward_layernorm for pre_mlp_prefix hook.")  # 結構不符時直接中止。
                handles.append(
                    pre_feedforward_layernorm.register_forward_pre_hook(
                        self._make_deep_prefix_pre_hook(
                            prefix_key="pre_mlp_prefix",
                            layer_idx=layer_idx,
                            prefix_positions=prefix_positions,
                            roi_DxItems=roi_DxItems,
                            hook_name="pre_feedforward_layernorm pre-hook",
                        ),
                        with_kwargs=True,
                    )
                )

            if "pre_ple_prefix" in active_prefix_keys:
                per_layer_input_gate = getattr(layer, "per_layer_input_gate", None)
                if not isinstance(per_layer_input_gate, nn.Module):
                    raise RuntimeError(f"text_backbone.layers[{layer_idx}] has no nn.Module per_layer_input_gate for pre_ple_prefix hook.")  # 使用者要求啟用但模型不支援時直接中止。
                handles.append(
                    per_layer_input_gate.register_forward_pre_hook(
                        self._make_deep_prefix_pre_hook(
                            prefix_key="pre_ple_prefix",
                            layer_idx=layer_idx,
                            prefix_positions=prefix_positions,
                            roi_DxItems=roi_DxItems,
                            hook_name="per_layer_input_gate pre-hook",
                        ),
                        with_kwargs=True,
                    )
                )

        return handles

    def _get_active_deep_prefix_keys(self) -> List[str]:
        if not hasattr(self, "prefix_module_dict"):
            return []
        return [prefix_key for prefix_key in DEEP_PREFIX_KEYS if prefix_key in self.prefix_module_dict]

    def _make_deep_prefix_pre_hook(
        self,
        prefix_key: str,
        layer_idx: int,
        prefix_positions: List[int],
        roi_DxItems: List[str],
        hook_name: str,
    ):
        def hook(module, args, kwargs):
            hidden_states, hidden_state_key = self._locate_hidden_states_in_hook_inputs(
                args=args,
                kwargs=kwargs,
                hook_name=hook_name,
            )
            new_hidden_states = self._inject_layerwise_deep_prefix(
                hidden_states=hidden_states,
                layer_idx=layer_idx,
                prefix_positions=prefix_positions,
                roi_DxItems=roi_DxItems,
                prefix_key=prefix_key,
            )
            return self._replace_hidden_states_in_hook_inputs(
                args=args,
                kwargs=kwargs,
                hidden_state_key=hidden_state_key,
                new_hidden_states=new_hidden_states,
            )

        return hook

    def _make_deep_prefix_post_hook(
        self,
        prefix_key: str,
        layer_idx: int,
        prefix_positions: List[int],
        roi_DxItems: List[str],
    ):
        def hook(module, args, kwargs, output):
            if torch.is_tensor(output):
                return self._inject_layerwise_deep_prefix(
                    hidden_states=output,
                    layer_idx=layer_idx,
                    prefix_positions=prefix_positions,
                    roi_DxItems=roi_DxItems,
                    prefix_key=prefix_key,
                )
            if isinstance(output, tuple) and len(output) > 0 and torch.is_tensor(output[0]):
                new_first = self._inject_layerwise_deep_prefix(
                    hidden_states=output[0],
                    layer_idx=layer_idx,
                    prefix_positions=prefix_positions,
                    roi_DxItems=roi_DxItems,
                    prefix_key=prefix_key,
                )
                return (new_first,) + output[1:]
            raise ValueError(f"Unable to locate tensor hidden_states in decoder layer post-hook output: {type(output)}.")

        return hook

    def _locate_hidden_states_in_hook_inputs(
        self,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        hook_name: str,
    ) -> Tuple[torch.Tensor, Optional[str]]:
        if len(args) > 0:
            hidden_states = args[0]
            hidden_state_key = None
        elif "hidden_states" in kwargs:
            hidden_states = kwargs["hidden_states"]
            hidden_state_key = "hidden_states"
        elif "x" in kwargs:
            hidden_states = kwargs["x"]
            hidden_state_key = "x"
        elif "input" in kwargs:
            hidden_states = kwargs["input"]
            hidden_state_key = "input"
        else:
            raise ValueError(f"Unable to locate hidden_states in {hook_name} inputs.")

        if hidden_states is None or not torch.is_tensor(hidden_states) or hidden_states.ndim != 3:
            shape = tuple(hidden_states.shape) if torch.is_tensor(hidden_states) else None
            raise ValueError(f"Expected hidden_states with shape (B, S, H) in {hook_name}, but got {type(hidden_states)} with shape {shape}.")

        return hidden_states, hidden_state_key

    def _replace_hidden_states_in_hook_inputs(
        self,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        hidden_state_key: Optional[str],
        new_hidden_states: torch.Tensor,
    ) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
        if hidden_state_key is None:
            return (new_hidden_states,) + args[1:], kwargs
        new_kwargs = dict(kwargs)
        new_kwargs[hidden_state_key] = new_hidden_states
        return args, new_kwargs

    def _inject_layerwise_deep_prefix(self,
        hidden_states: torch.Tensor,
        layer_idx: int,
        prefix_positions: List[int],
        roi_DxItems: List[str],
        prefix_key: str,
    ) -> torch.Tensor:
        if hidden_states.ndim != 3:
            raise ValueError(
                f"Expected hidden_states with shape (B, S, H), got {tuple(hidden_states.shape)}."
            )
        if len(prefix_positions) != len(roi_DxItems):
            raise ValueError(
                f"len(prefix_positions)={len(prefix_positions)} != len(roi_DxItems)={len(roi_DxItems)}."
            )

        batch_size, seq_len, hidden_dim = hidden_states.shape
        if batch_size != 1:
            raise ValueError(
                f"Current deep prefix injection expects batch_size=1, but got {batch_size}."
            )
        if hidden_dim != self.hidden_size:
            raise ValueError(
                f"Hidden dim mismatch during deep prefix injection: expected {self.hidden_size}, got {hidden_dim}."
            )

        if prefix_key not in DEEP_PREFIX_KEYS:
            raise ValueError(f"Unknown deep prefix key: {prefix_key}. Expected one of {DEEP_PREFIX_KEYS}.")
        if prefix_key not in self.prefix_module_dict:
            raise RuntimeError(f"Deep prefix module '{prefix_key}' is not initialized.")

        deep_prefix = self.prefix_module_dict[prefix_key]
        if len(prefix_positions) == 0:
            return hidden_states

        segments = []
        cursor = 0
        for roi_idx, insert_pos in enumerate(prefix_positions):
            DxItem = roi_DxItems[roi_idx]
            if DxItem not in deep_prefix:
                raise ValueError(f"{prefix_key} for ROI[{roi_idx}] DxItem '{DxItem}' is not initialized.")

            layer_prefix = deep_prefix[DxItem].get(layer_idx)
            if layer_prefix.ndim != 2:
                raise ValueError(
                    f"{prefix_key}['{DxItem}'][layer={layer_idx}] must be 2D (P, H), got {tuple(layer_prefix.shape)}."
                )
            if layer_prefix.shape[0] != self.prefix_len or layer_prefix.shape[1] != hidden_dim:
                raise ValueError(
                    f"{prefix_key}['{DxItem}'][layer={layer_idx}] shape={tuple(layer_prefix.shape)}, "
                    f"expected ({self.prefix_len}, {hidden_dim})."
                )

            start = int(insert_pos)
            end = start + self.prefix_len
            if start < 0 or end > seq_len:
                raise ValueError(
                    f"Invalid deep prefix span [{start}, {end}) for sequence length {seq_len}."
                )
            if start < cursor:
                raise ValueError(
                    f"Deep prefix spans must be sorted and non-overlapping, but got start={start} after cursor={cursor}."
                )

            layer_prefix_device = layer_prefix.to(
                device=hidden_states.device,
                dtype=hidden_states.dtype,
            )

            if start > cursor:
                segments.append(hidden_states[:, cursor:start, :])
            segments.append(hidden_states[:, start:end, :] + layer_prefix_device.unsqueeze(0))
            cursor = end

        if cursor < seq_len:
            segments.append(hidden_states[:, cursor:, :])

        return torch.cat(segments, dim=1)



    def prefill(self, 
        inputs_embeds: torch.Tensor,
        attention_mask: torch.Tensor,
        per_layer_inputs: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:

        log_print(f"context_len={inputs_embeds.shape}")
        forward_kwargs = {
            "inputs_embeds": inputs_embeds, 
            "attention_mask": attention_mask, 
            "output_hidden_states": False, 
            "use_cache": False,
        }
        if per_layer_inputs is not None:
            forward_kwargs["per_layer_inputs"] = per_layer_inputs
        out = self.text_backbone(**forward_kwargs)

        return out.last_hidden_state

    def forward(self, 
        case: Case, 
    ) -> Dict[str, Any]:
        
        inputs, roi_DxItems = self.build_inputs(
            case=case
        )
        merged_embeds, per_layer_inputs = self.get_merged_embeds(
            inputs=inputs,
        )

        new_embeds, attn_mask, prefix_positions, per_layer_inputs = self.insert_prefix_embeds(
            input_ids=inputs["input_ids"],
            merged_embeds=merged_embeds,
            roi_DxItems=roi_DxItems,
            per_layer_inputs=per_layer_inputs,
        )

        new_embeds = move_to_device(new_embeds, self.device)
        attn_mask = move_to_device(attn_mask, self.device)
        per_layer_inputs = move_to_device(per_layer_inputs, self.device) if per_layer_inputs is not None else None

        handles = self._register_deep_prefix_hooks(
            prefix_positions=prefix_positions,
            roi_DxItems=roi_DxItems,
        )
        try:
            last_hidden = self.prefill(
                inputs_embeds=new_embeds,
                attention_mask=attn_mask,
                per_layer_inputs=per_layer_inputs,
            )
        finally:
            for handle in handles:
                handle.remove()

        return {
            "last_hidden": last_hidden,
            "prefix_positions": prefix_positions,
        }

    @staticmethod
    def _normalize_batch(
        batch: Any, 
    ) -> List[Any]:
        if batch is None:
            return []
        if isinstance(batch, list):
            return batch
        if isinstance(batch, tuple):
            return list(batch)
        return [batch]

    def _maybe_log_deep_prefix_norms(self,
    ):
        if not getattr(self, "deep_prefix_debug_log", False):
            return
        self._deep_prefix_debug_counter += 1
        freq = max(1, int(getattr(self, "deep_prefix_debug_log_freq", 50)))
        if self._deep_prefix_debug_counter % freq != 0:
            return

        if not hasattr(self, "prefix_module_dict"):
            return
        active_prefix_keys = self._get_active_deep_prefix_keys()
        if len(active_prefix_keys) == 0:
            return

        with torch.no_grad():
            layer_modules = getattr(self.text_backbone, "layers", None)
            if layer_modules is None or len(layer_modules) == 0:
                return

            layer_indices = [0, len(layer_modules) // 2, len(layer_modules) - 1]
            seen = set()
            layer_indices = [i for i in layer_indices if not (i in seen or seen.add(i))]

            stats = []
            for prefix_key in active_prefix_keys:
                deep_prefix = self.prefix_module_dict[prefix_key]
                for layer_idx in layer_indices:
                    layer_norm_acc = 0.0
                    count = 0
                    for DxItem in self.DxItem_list:
                        if DxItem not in deep_prefix:
                            continue
                        w = deep_prefix[DxItem].get(layer_idx)
                        layer_norm_acc += float(w.detach().float().norm(p=2).item())
                        count += 1
                    if count > 0:
                        stats.append(f"{prefix_key}/L{layer_idx}:{layer_norm_acc / count:.4f}")

            if len(stats) > 0:
                log_print(f"[DeepPrefixDebug] step={self._deep_prefix_debug_counter} mean L2 norm by layer -> {' | '.join(stats)}")



    @classmethod
    def from_config(cls, 
        cfg: Any,
    ):
        log_print(f"Loading Model...")
        log_print(f"model_name: {cfg.model_name}")

        model_builder = modelBuilder(
            weight_path=cfg.weight_path, 
        )
        vlm_model, vlm_processor, _, _, vlm_max_senLen, _ = model_builder.create_language_model(
            model_name=cfg.model_name, 
            project_name="CLEE", 
            freeze_weight=True, 
            load_visual_processor=True, 
            torch_dtype=getattr(cfg, "torch_dtype", torch.bfloat16),
            config_dict={
                "use_bidirectional_attention": True, 
                "attn_implementation": getattr(cfg, "attn_implementation", None), 
                "pp_vision_split_index": getattr(cfg, "pp_vision_split_index", None),
            }, 
            pp_num_gpus=getattr(cfg, "pp_num_gpus", None),
        )
        if vlm_model.config.model_type in ["gemma4"]:
            vlm_processor.max_soft_tokens = cfg.max_soft_tokens


        clee = cls(
            system_prompt_path=cfg.system_prompt_path,
            temperature=cfg.temperature,
            input_img=getattr(cfg, "input_img", True),
            device=cfg.device
        )
        clee.deep_prefix_debug_log = bool(getattr(cfg, "deep_prefix_debug_log", True))
        clee.deep_prefix_debug_log_freq = int(getattr(cfg, "deep_prefix_debug_log_freq", 50))

        clee.init_vlm_model(
            vlm_processor=vlm_processor,
            vlm_model=vlm_model, 
            max_senLen=vlm_max_senLen,
        )
        clee.init_prefix(
            DxItem_list=cfg.DxItem_list, 
            active_DxItem_list=getattr(cfg, "active_DxItem_list", None),
            declared_DxResult_dict=getattr(
                cfg,
                "declared_DxResult_dict",
                None,
            ),
            active_DxResult_dict=getattr(
                cfg,
                "active_DxResult_dict",
                None,
            ),
            prefix_len=cfg.prefix_len,
            use_pre_trans_prefix=bool(getattr(cfg, "use_pre_trans_prefix", True)), 
            use_post_trans_prefix=bool(getattr(cfg, "use_post_trans_prefix", False)), 
            use_pre_attn_prefix=bool(getattr(cfg, "use_pre_attn_prefix", False)), 
            use_pre_mlp_prefix=bool(getattr(cfg, "use_pre_mlp_prefix", False)), 
            use_pre_ple_prefix=bool(getattr(cfg, "use_pre_ple_prefix", False)), 
        )
        clee.init_sep(
            sep_str=cfg.sep_str, 
            boc_str=cfg.boc_str, 
        )

        return clee
