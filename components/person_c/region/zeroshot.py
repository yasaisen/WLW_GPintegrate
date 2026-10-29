"""
zeroshot.py -- CONCH text-tower zero-shot classification of clusters
against the CRC vocab, filtered down to EPI/TUM (the two categories ROI
actually proposes regions for). Ported (not imported -- EXPERIMENTS is a
read-only nano5-maintained mirror) from EXPERIMENTS/SEMANTIC/
ClusterZeroShot.py's load_conch_text_model / expand_templates_patch /
encode_text_centroids / cluster_dominant_category.

Classifies against the FULL 9-category CRC vocab (ADI/BACK/DEB/LYM/MUC/
MUS/EPI/STR/TUM) via softmax, same as the reference -- the other 7
categories' probability mass is real signal for whether EPI/TUM actually
wins a cluster's argmax, not noise to discard by only encoding 2 prompts.
Clusters whose dominant category isn't EPI or TUM are simply not region
proposals (ROI only proposes EPI/TUM regions, per user design decision).

Default vocab path reads straight from the EXPERIMENTS git mirror
(DESCRIPTION/CRC/100k_v2.json) -- unlike the CONCH weights (too large for
git, transferred by hand from nano5), this is a small JSON already pulled
down with the rest of the repo. Reading a data file from EXPERIMENTS at
runtime is fine (only editing/committing to it is off-limits) -- see
[[project-experiments-evaluation-split]].
"""
import colorsys
import sys

import numpy as np
import torch
import torch.nn.functional as F

_CRC_JSON_DEFAULT = None  # always passed explicitly from config
EPI_NAME, TUM_NAME = "EPI", "TUM"

# BCSS's own 20-category vocab (2026-09-16 user request) -- BCSS's classes
# aren't the CRC/BRACS 9-category CRC-100k scheme, they're breast-tissue
# specific (see PIPELINE/DATASET/Convert.py's _BCSS_CODES, the ground-truth
# mask legend these names/codes are copied from verbatim so GT and zero-shot
# use the identical name<->code<->color mapping). subtypes/templates content
# lives in the JSON; only the name<->code<->color mapping (for stage-output
# colors) is duplicated here.
_BCSS_JSON_DEFAULT = None  # always passed explicitly from config

_BCSS_CODES = {
    1: "tumor", 2: "stroma", 3: "lymphocytic_infiltrate", 4: "necrosis_or_debris",
    5: "glandular_secretions", 6: "blood", 8: "metaplasia_NOS", 9: "fat",
    10: "plasma_cells", 11: "other_immune_infiltrate", 12: "mucoid_material",
    13: "normal_acinus_or_duct", 14: "lymphatics", 15: "undetermined", 16: "nerve",
    17: "skin_adnexa", 18: "blood_vessel", 19: "angioinvasion", 20: "dcis", 21: "other",
}


def _bcss_color(code):
    # Same golden-ratio hue step as Convert.py's _bcss_color -- kept in
    # sync by hand (not imported, see this module's own docstring on
    # EXPERIMENTS being read-only-at-runtime doesn't apply here, this is
    # just avoiding a cross-package import for one small function) so a
    # BCSS class renders the SAME color in the GT viewer and in ROI's own
    # zeroshot-stage output.
    hue = (code * 0.6180339887) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.92)
    return (int(r * 255), int(g * 255), int(b * 255))

# distinct colors for all 9 CRC categories (ADI/BACK/DEB/LYM/MUC/MUS/EPI/STR/TUM)
# -- used by the "zeroshot" stage output (every cluster's full classification,
# not just the EPI/TUM ones that survive into the final region-proposal stage).
# ColorBrewer "Paired"-derived qualitative palette (colorblind-considered,
# built for exactly this job -- categorical overlays on tissue imagery) --
# swapped in 2026-09-11 for the original pure-primary set (255,255,0) /
# (0,255,255) / (255,0,255) / (0,0,255), which read as neon/cartoonish
# rather than a figure-appropriate scheme. Semantic roles kept familiar:
# red=tumor, green=epithelium, blue=stroma.
CRC_COLORS = {
    "ADI": (253, 191, 111), "BACK": (176, 176, 176), "DEB": (177, 89, 40),
    "LYM": (230, 194, 41), "MUC": (166, 206, 227), "MUS": (202, 178, 214),
    "EPI": (51, 160, 44), "STR": (31, 120, 180), "TUM": (227, 26, 28),
}

BCSS_COLORS = {name: _bcss_color(code) for code, name in _BCSS_CODES.items()}

# Per-dataset vocab: which JSON to classify clusters against, the full
# palette for the "zeroshot" stage (every cluster gets a color), and which
# category name(s) survive into the "proposal" stage. BRACS/BACH share the
# CRC vocab and its original EPI+TUM proposal filter ("all epithelium,
# benign or malignant"). BCSS's own epithelial-lineage equivalent --
# confirmed with user 2026-09-16 -- is malignant (tumor, dcis) + benign
# (normal_acinus_or_duct, metaplasia_NOS) epithelium.
VOCAB_CONFIG = {
    "BRACS": {"json": _CRC_JSON_DEFAULT, "colors": CRC_COLORS, "proposal_cats": (EPI_NAME, TUM_NAME)},
    "BACH": {"json": _CRC_JSON_DEFAULT, "colors": CRC_COLORS, "proposal_cats": (EPI_NAME, TUM_NAME)},
    "BCSS": {"json": _BCSS_JSON_DEFAULT, "colors": BCSS_COLORS,
             "proposal_cats": ("tumor", "dcis", "normal_acinus_or_duct", "metaplasia_NOS")},
}


def vocab_config(dataset):
    return VOCAB_CONFIG[dataset]


def load_conch_text_model(lib_path, ckpt_path, force_image_size, device):
    """CONCH text tower only -- no vision forward pass (this reuses
    whatever features utils/preprocess.py already extracted)."""
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    from conch.open_clip_custom import create_model_from_pretrained, get_tokenizer
    tokenizer = get_tokenizer()
    model, _ = create_model_from_pretrained("conch_ViT-B-16", ckpt_path,
                                             force_image_size=force_image_size)
    model = model.to(device).eval()
    return model, tokenizer


def load_crc_categories(path=_CRC_JSON_DEFAULT):
    import json
    return json.load(open(path, encoding="utf-8"))


def expand_templates_patch(cat, max_subtypes, max_templates):
    templates = list(cat["templates"])[:max_templates]
    subtypes = cat.get("subtypes")
    if subtypes and any("{subtype}" in t for t in templates):
        subtypes = list(subtypes)[:max_subtypes]
        return [t.replace("{subtype}", s) for s in subtypes for t in templates]
    return templates


def encode_text_centroids(model, tokenizer, cats, device, max_subtypes=8, max_templates=8):
    """cats -> (centroids[n_cat,512] float32 numpy, cat_names[n_cat])."""
    from conch.open_clip_custom import tokenize
    cat_names = [c["name"] for c in cats]
    centroids = []
    for cat in cats:
        texts = expand_templates_patch(cat, max_subtypes, max_templates)
        embs = []
        for s in range(0, len(texts), 256):
            tok = tokenize(texts=texts[s:s + 256], tokenizer=tokenizer).to(device)
            with torch.inference_mode():
                embs.append(F.normalize(model.encode_text(tok), dim=-1))
        t = torch.cat(embs, 0)
        centroids.append(F.normalize(t.mean(0, keepdim=True), dim=-1))
    return torch.cat(centroids, 0).cpu().numpy(), cat_names


def classify_cells(feat, centroids, zs_temp=0.1, device=None):
    """feat[N,512] (L2-unit, same space as centroids) -> probs[N,n_cat] via
    softmax(cosine_sim / zs_temp). GPU matmul, not numpy -- at real WSI
    scale (N in the millions) `feat @ centroids.T` as a plain numpy CPU
    matmul was the actual cost of the whole zero-shot stage (measured:
    92.6s total for a step that's otherwise nothing but this one matmul +
    a softmax), device=None falls back to CPU (fine for small/synthetic
    inputs, not for a real WSI's full cell count)."""
    feat_t = torch.from_numpy(feat.astype(np.float32))
    centroids_t = torch.from_numpy(centroids.astype(np.float32))
    if device is not None:
        feat_t = feat_t.to(device)
        centroids_t = centroids_t.to(device)
    sim = feat_t @ centroids_t.T
    probs = F.softmax(sim / zs_temp, dim=1)
    return probs.cpu().numpy()


def cluster_dominant_category(labels, cell_probs, n_cat, n_clusters=None):
    """Sums each cluster's member cells' probability vectors, argmax ->
    the cluster's own aggregate label. Returns (per_cell_dominant[N] int,
    per_cluster_dominant[K] int)."""
    labels = np.asarray(labels)
    cell_probs = np.asarray(cell_probs, np.float64)
    k = n_clusters if n_clusters is not None else (int(labels.max()) + 1 if labels.size else 0)
    cluster_sum = np.zeros((k, n_cat), np.float64)
    for kk in range(k):
        m = labels == kk
        if m.any():
            cluster_sum[kk] = cell_probs[m].sum(axis=0)
    dominant = cluster_sum.argmax(axis=1)
    return dominant[labels].astype(np.int64), dominant


def classify_clusters(labels, feat, model, tokenizer, device, K,
                       zs_temp=0.1, max_subtypes=8, max_templates=8,
                       crc_json_path=_CRC_JSON_DEFAULT):
    """One CONCH text-tower classification pass, full 9-category CRC vocab.
    labels[N] (Partition.py cluster ids), feat[N,512] (same maskclip
    features Partition.py clustered on -- CONCH's own space is already
    text-aligned, no separate embedding needed here).

    Returns (cat_names[9], cluster_dominant[K] int index into cat_names) --
    the RAW classification result, before any EPI/TUM filtering. Both the
    "zeroshot" stage output (every cluster, all 9 categories) and the
    "proposal" stage output (EPI/TUM only) are thin views over this SAME
    pass -- classification only runs once regardless of how many stage
    outputs the caller wants."""
    cats = load_crc_categories(crc_json_path)
    centroids, cat_names = encode_text_centroids(model, tokenizer, cats, device,
                                                   max_subtypes, max_templates)
    probs = classify_cells(feat, centroids, zs_temp, device=device)
    _, cluster_dominant = cluster_dominant_category(labels, probs, len(cat_names), K)
    return cat_names, cluster_dominant


def full_cluster_names_colors(cat_names, cluster_dominant, colors=CRC_COLORS):
    """Every cluster's own dominant category (all of the vocab's own
    categories are possible), for the "zeroshot" stage output -- no
    filtering, every cluster gets a name. `colors` is the dataset's own
    full palette (VOCAB_CONFIG[dataset]["colors"])."""
    names = [cat_names[d] for d in cluster_dominant]
    out_colors = [colors.get(n, (150, 150, 150)) for n in names]
    return names, out_colors


def proposal_names_colors(cat_names, cluster_dominant, K, proposal_cats, colors=CRC_COLORS):
    """Restricted to clusters whose dominant category is in `proposal_cats`
    (every other cluster is simply not a region proposal), for the
    "proposal" stage output. `proposal_cats`/`colors` come from the
    dataset's own VOCAB_CONFIG entry -- generalizes the original BRACS/CRC-
    only EPI+TUM filter to any dataset's own proposal-category set.

    Returns (names[K] with None for non-proposal clusters, colors[K] RGB
    tuples, keep[K] bool -- which cluster ids survive into the geojson
    export)."""
    keep_idx = {cat_names.index(c) for c in proposal_cats if c in cat_names}
    names = [None] * K
    out_colors = [(0, 0, 0)] * K
    keep = np.zeros(K, dtype=bool)
    for k in range(K):
        d = cluster_dominant[k]
        if d in keep_idx:
            n = cat_names[d]
            names[k], out_colors[k], keep[k] = n, colors.get(n, (150, 150, 150)), True
    return names, out_colors, keep
