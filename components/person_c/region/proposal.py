"""One WSI -> region-proposal polygons (level-0 pixel space).

Trimmed port of PIPELINE/ROI/RegionProposal.py: same CONCH dense features ->
vMF clustering -> zero-shot cluster naming chain, but only the ``proposal``
stage is returned and every path/hyperparameter comes from the component
config instead of argparse defaults. Heavy imports (torch, openslide) happen
inside ``propose_regions`` so contract tests stay CPU/stdlib only.
"""

from __future__ import annotations

from typing import Any, Mapping


def propose_regions(wsi_path: str, cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return GeoJSON Polygon features (level-0 px) for the proposal categories.

    ``cfg`` is the already-resolved region config (absolute ``conch_lib_path``,
    ``conch_checkpoint``, ``vocab_json``; see ``interest_pattern._region_cfg``).
    Raises on CUDA-unavailable, unreadable slide or any model failure.
    """

    import numpy as np
    import torch

    from components.person_c.region import partition as partition_mod
    from components.person_c.region import preprocess as preprocess_mod
    from components.person_c.region import zeroshot as zeroshot_mod

    device = torch.device(cfg["device"])
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("person_c requested CUDA, but PyTorch cannot access a CUDA device")

    fields = [int(f) for f in cfg["fields"]]
    mag = float(cfg["mag"])
    K = int(cfg["K"])
    if not fields:
        raise ValueError("region.fields must not be empty")

    field_feats = []
    idx_sets = []
    Hg = Wg = cell_px = None
    model = tokenizer = None
    for fi, field in enumerate(fields):
        is_base = fi == 0
        force_image_size = max(16, round(field * mag / 40.0 / 16.0) * 16)
        m, pp = preprocess_mod.load_conch_vision(
            cfg["conch_lib_path"], cfg["conch_checkpoint"], force_image_size, device
        )
        if is_base:
            model = m
            from conch.open_clip_custom import get_tokenizer

            tokenizer = get_tokenizer()
        ext = preprocess_mod.extract_features(
            wsi_path,
            m,
            pp,
            device,
            field=field,
            mag=mag,
            overlap=float(cfg["overlap"]),
            batch_size=int(cfg["batch_size"]),
            num_workers=int(cfg["num_workers"]),
            pin_memory=True,
        )
        if Hg is None:
            Hg, Wg, cell_px = ext["Hg"], ext["Wg"], ext["cell_px"]
        elif ext["Hg"] != Hg or ext["Wg"] != Wg or abs(ext["cell_px"] - cell_px) > 1e-6:
            raise ValueError(
                f"field={field}: grid does not match the base field; every region.fields "
                "value must share one region.mag"
            )
        field_feats.append((ext["idx"], ext["feat"], ext["feat_patch"] if is_base else None))
        idx_sets.append(set(ext["idx"].tolist()))
        if not is_base:
            del m, pp
            if device.type == "cuda":
                torch.cuda.empty_cache()

    common = np.array(sorted(set.intersection(*idx_sets)), dtype=np.int64)
    if common.size == 0:
        return []

    def _select(idx_full, arr):
        pos = {int(c): i for i, c in enumerate(idx_full)}
        return arr[np.array([pos[int(c)] for c in common], dtype=np.int64)]

    base_idx, base_feat, base_patch = field_feats[0]
    feat = _select(base_idx, base_feat)

    valid_grid = np.zeros(Hg * Wg, dtype=bool)
    valid_grid[common] = True
    mu_grid = np.zeros((Hg * Wg, feat.shape[1]), dtype=np.float16)
    mu_grid[common] = feat
    surrounding, _ = partition_mod.surrounding_pool(
        mu_grid, valid_grid, Wg, Hg, radius=int(cfg["radius"]), device=device
    )

    blocks = [feat.astype(np.float32), surrounding[common].astype(np.float32)]
    if cfg["use_patch"]:
        blocks.append(_select(base_idx, base_patch).astype(np.float32))
    for idx_full, feat_full, _ in field_feats[1:]:
        blocks.append(_select(idx_full, feat_full).astype(np.float32))
    if int(cfg["pca_dim"]) > 0:
        blocks = [partition_mod.pca_reduce(b, int(cfg["pca_dim"])) for b in blocks]

    labels, _ = partition_mod.cluster_vmf_multichannel(
        blocks, K=K, seed=int(cfg["seed"]), device=device
    )

    vocab = zeroshot_mod.vocab_config(cfg["vocab"])
    cat_names, cluster_dominant = zeroshot_mod.classify_clusters(
        labels,
        feat,
        model,
        tokenizer,
        device,
        K=K,
        zs_temp=float(cfg["zs_temp"]),
        crc_json_path=cfg["vocab_json"],
    )
    lab2d = np.full(Hg * Wg, -1, dtype=np.int32)
    lab2d[common] = labels
    lab2d = lab2d.reshape(Hg, Wg)

    names, colors, _ = zeroshot_mod.proposal_names_colors(
        cat_names,
        cluster_dominant,
        K,
        tuple(cfg["proposal_categories"]) or vocab["proposal_cats"],
        colors=vocab["colors"],
    )
    return partition_mod.lab2d_to_geojson_features(
        lab2d, K, cell_px, names, colors, drop_holes=True
    )
