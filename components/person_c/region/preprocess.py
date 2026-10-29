"""
preprocess.py -- CONCH (maskclip/dense-token) feature extraction for one
WSI, IN MEMORY, no disk cache. Ported (not imported -- EXPERIMENTS is a
read-only nano5-maintained mirror on this machine) from EXPERIMENTS/
HELPER/Preprocessing.py's tissue segmentation + crop-lattice + centre-
weighted accumulation math, and from EXPERIMENTS/CLUSTER/Partition.py's
maskclip TileExtractor (documented there as "verbatim from
HELPER/Preprocessing.py's TileExtractor").

Deliberately simplified from the reference: ONE (field, mag) config, not a
multi-config sweep -- ROI runs one region-proposal pass per WSI, it's not
a research sweep tool. Everything below stops at returning
(idx, feat, Hg, Wg, cell_px, ms) in memory; the reference's
save_compact_cache/load_compact_cache (disk I/O) is intentionally not
ported at all.
"""
import math
import resource
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset


def _rss_gb():
    """Process peak RSS so far, in GB (ru_maxrss is KiB on Linux, a
    running high-water mark). Diagnostic only -- for OOM localisation,
    same technique the reference (CLUSTER/Partition.py's own _rss_gb)
    uses for the same reason."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


# ── tiling geometry (ported from HELPER/Preprocessing.py) ──────────────────

def field_step(field, overlap):
    """Overlap stride for one field: step = round(field*(1-overlap))."""
    return max(1, round(field * (1.0 - overlap)))


def segment_tissue(slide, mask_cell_px=32, sat_threshold=5, blur_kernel_px=7,
                    close_kernel_px=4, min_tissue_area=100000.0, min_hole_area=1000000.0):
    """Tissue foreground mask: median blur -> saturation threshold ->
    morphological close -> contour-hierarchy area/hole filtering. Returns
    (mask[Hm,Wm] bool, ms = mask px / level-0 px)."""
    mpp = float(slide.properties.get("openslide.mpp-x") or 0.25)
    cell_px = mask_cell_px
    W0, H0 = slide.level_dimensions[0]
    w0, h0 = max(1, round(W0 / cell_px)), max(1, round(H0 / cell_px))

    lvl = slide.get_best_level_for_downsample(cell_px)
    raw = slide.read_region((0, 0), lvl, slide.level_dimensions[lvl]).convert("RGB")
    arr = np.asarray(raw.resize((w0, h0), Image.LANCZOS))
    ms = w0 / W0

    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    med = cv2.medianBlur(hsv[..., 1], blur_kernel_px)
    _, bw = cv2.threshold(med, sat_threshold, 255, cv2.THRESH_BINARY)
    if close_kernel_px > 0:
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                               np.ones((close_kernel_px, close_kernel_px), np.uint8))

    mask_px_um2 = (mpp / ms) ** 2
    at_px = min_tissue_area / mask_px_um2
    ah_px = min_hole_area / mask_px_um2

    cnts, hier = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    mask = np.zeros(bw.shape, np.uint8)
    if hier is not None:
        hier = np.squeeze(hier, axis=0)[:, 2:]
        for i in np.flatnonzero(hier[:, 1] == -1):
            holes = np.flatnonzero(hier[:, 1] == i)
            area = cv2.contourArea(cnts[i]) - sum(cv2.contourArea(cnts[h]) for h in holes)
            if area <= at_px:
                continue
            cv2.drawContours(mask, [cnts[i]], -1, 1, thickness=cv2.FILLED)
            for h in holes:
                if cv2.contourArea(cnts[h]) > ah_px:
                    cv2.drawContours(mask, [cnts[h]], -1, 0, thickness=cv2.FILLED)
    return mask.astype(bool), ms


def build_lattice_coords(W, H, box, step, tissue, ms):
    """Top-left corners of box x box level0 crops, spaced `step`,
    tissue-filtered, edge-clamped so the far edge is always covered even
    when (W-box) isn't an exact multiple of step."""
    xs = list(range(0, max(1, W - box + 1), step))
    if xs[-1] != W - box:
        xs.append(max(0, W - box))
    ys = list(range(0, max(1, H - box + 1), step))
    if ys[-1] != H - box:
        ys.append(max(0, H - box))
    coords = [(x, y) for y in ys for x in xs]
    if tissue is not None:
        Hm, Wm = tissue.shape
        kept = []
        for x, y in coords:
            mx0, my0 = int(x * ms), int(y * ms)
            mx1, my1 = int((x + box) * ms) + 1, int((y + box) * ms) + 1
            sub = tissue[my0:min(my1, Hm), mx0:min(mx1, Wm)]
            if sub.size and sub.any():
                kept.append((x, y))
        coords = kept
    return coords


def compact_cell_map(coords, grid_eff, cell, Hg, Wg):
    """Per-crop -> grid_eff x grid_eff block of GLOBAL flat cell ids on a
    (Hg,Wg) grid. Returns (cells[n_cells] sorted ascending,
    comp[n,grid_eff^2] index into `cells`, ok[n,grid_eff^2] bool)."""
    col = np.arange(grid_eff)
    px = coords[:, 0].astype(np.float64)
    py = coords[:, 1].astype(np.float64)
    GI = np.floor(px[:, None] / cell + col + 0.5).astype(np.int64)
    GJ = np.floor(py[:, None] / cell + col + 0.5).astype(np.int64)
    vcol = (GI >= 0) & (GI < Wg)
    vrow = (GJ >= 0) & (GJ < Hg)
    flat_all = np.repeat(GJ, grid_eff, axis=1) * Wg + np.tile(GI, (1, grid_eff))
    ok = np.repeat(vrow, grid_eff, axis=1) & np.tile(vcol, (1, grid_eff))
    cells = np.unique(flat_all[ok])
    comp_lut = np.full(Hg * Wg, -1, dtype=np.int64)
    comp_lut[cells] = np.arange(cells.size)
    comp = comp_lut[np.clip(flat_all, 0, Hg * Wg - 1)]
    return cells, comp, ok


def spline_weight_grid(grid_eff):
    """2D separable Hann window over a grid_eff x grid_eff crop-relative
    position grid -- weight=1 at the crop's own centre, taper to (floored)
    0 at its edges. Makes overlapping crops' contribution to a shared
    fine cell favour whichever crop centres that cell, instead of a flat
    average."""
    N = grid_eff
    if N <= 1:
        return torch.ones(max(1, N) ** 2)
    i = np.arange(N, dtype=np.float64)
    w1 = (0.5 - 0.5 * np.cos(2 * np.pi * i / (N - 1))).astype(np.float32)
    w2 = np.outer(w1, w1).reshape(-1)
    w2 = np.maximum(w2, 1e-2)
    return torch.from_numpy(w2)


class _CropDataset(Dataset):
    """Reads a native_px x native_px (level-0 coordinate space) field of
    view at each lattice coord, but from whichever PYRAMID LEVEL actually
    matches the target downsample -- not always level 0. read_region's
    `location` is always level-0 coordinates regardless of which level you
    read from; only the level index + read size (in THAT level's own
    pixels) change. Reading level 0 in full and resizing down in software
    (the original approach) decodes far more JPEG tile data than the
    model will ever use once force_image_size is smaller than native_px --
    e.g. field=1024/mag=20 needs a 2x downsample, but a real Aperio SVS's
    levels commonly jump 1x->4x->16x (no 2x available) so THAT config gets
    no benefit; field=1024/mag=10 needs 4x, which DOES land on a real
    level on this dataset (verified via level_downsamples, 2026-09-10) --
    reading directly from that level avoids decoding level-0 detail that
    would just be thrown away by the resize anyway.

    Per-worker lazy OpenSlide handle (can't share a handle across a
    DataLoader fork)."""
    def __init__(self, wsi_path, coords, native_px, transform, read_level=0, read_size=None):
        self.wsi_path, self.coords, self.native_px, self.transform = \
            wsi_path, coords, native_px, transform
        self.read_level = read_level
        self.read_size = read_size or native_px   # size AT read_level, not level-0 px
        self._slide = None

    def _handle(self):
        if self._slide is None:
            import openslide
            self._slide = openslide.OpenSlide(self.wsi_path)
        return self._slide

    def __len__(self):
        return len(self.coords)

    def __getitem__(self, i):
        x, y = self.coords[i]
        img = self._handle().read_region(
            (x, y), self.read_level, (self.read_size, self.read_size)).convert("RGB")
        return self.transform(img), x, y


# ── CONCH maskclip dense-token feature head ─────────────────────────────────
# (ported from CLUSTER/Partition.py's _TileExtractor/_embed_image/
# _load_conch_vision, documented there as verbatim from Preprocessing.py)

def load_conch_vision(lib_path, ckpt_path, force_image_size, device):
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    from conch.open_clip_custom import create_model_from_pretrained
    model, preprocess = create_model_from_pretrained(
        "conch_ViT-B-16", ckpt_path, force_image_size=force_image_size)
    return model.to(device).eval(), preprocess


class MaskclipExtractor:
    """Dense per-token embeddings from ONE CONCH forward pass, two kinds:
      maskclip -- trunk tokens run through the contrastive attention
                  pooler (attn_pool_contrast -> ln_contrast ->
                  proj_contrast), 512-d, L2-normalised, the space CONCH's
                  text tower is aligned to -- what zero-shot classification
                  needs (utils/zeroshot.py), and what clustering used
                  exclusively before this class returned a second value.
      patch    -- the RAW trunk tokens themselves, BEFORE the pooler:
                  768-d, un-normalised on the reference's own disk cache
                  (EXPERIMENTS/HELPER/Preprocessing.py's `--kind patch`),
                  since other consumers there want that literal magnitude
                  (e.g. TransferPartition.py matching a GMM trained on raw
                  trunk tokens). Here it feeds the vMF clustering as an
                  extra channel instead (2026-09-11, user request: "PATCH
                  也要拿去用" -- don't cluster on maskclip's text-aligned
                  space alone), which assumes unit-norm inputs per channel
                  same as any other vMF channel (Banerjee kappa, the vMF
                  log-density) -- so extract_features L2-normalises this
                  after averaging, same treatment as the maskclip channel,
                  even though the on-disk reference convention doesn't.
                  patch is NEVER fed into zero-shot -- it's not in CONCH's
                  text-aligned space at all (different dimensionality, no
                  projection to align it), clustering-only.
    patch is a strict prefix of maskclip's own compute (maskclip = trunk
    -> pooler; patch = trunk, stop) -- returning both from one trunk call
    costs one extra tensor, not a second forward pass."""
    def __init__(self, model, grid, amp=True):
        self.model = model
        self.grid = grid
        self.amp = amp
        self.pooler = model.visual.attn_pool_contrast
        self.mha = self.pooler.attn
        self.d = self.mha.embed_dim
        self.vbias = (self.mha.in_proj_bias[2 * self.d:3 * self.d]
                      if self.mha.in_proj_bias is not None else None)

    @torch.inference_mode()
    def __call__(self, imgs):
        with torch.autocast(device_type=imgs.device.type, dtype=torch.bfloat16,
                             enabled=(self.amp and imgs.device.type == "cuda")):
            tokens = self.model.visual.trunk(imgs)
        L = tokens.shape[1]
        P = self.grid * self.grid
        if L != P:
            tokens = tokens[:, L - P:, :]
        tokens = tokens.float()
        patch = tokens                          # [B, grid*grid, 768], raw
        k = self.pooler.ln_k(tokens)
        v = F.linear(k, self.mha.v_proj_weight, self.vbias)
        z_ = self.mha.out_proj(v)
        z_ = self.model.visual.ln_contrast(z_)
        z_ = z_ @ self.model.visual.proj_contrast
        maskclip = F.normalize(z_, dim=-1)      # [B, grid*grid, 512]
        return maskclip, patch


# ── extraction entry point ──────────────────────────────────────────────────

def extract_features(wsi_path, model, preprocess, device, field=1024, mag=20.0,
                      overlap=0.5, cell_um=None, batch_size=16, num_workers=4,
                      pin_memory=True, tissue_params=None, need_patch=True):
    """One WSI -> in-memory dense CONCH maskclip features on a (Hg,Wg) fine
    cell grid. Returns dict(idx, feat[N,512] float16 L2-unit, Hg, Wg,
    cell_px (level0 px per fine cell), mpp_x).

    need_patch=False skips the feat_patch (768-dim) accumulator/return
    entirely -- default True preserves every existing caller's behavior
    (RegionProposal.py reads feat_patch for its base field), but a
    caller that only ever uses `feat` (maskclip, 512-dim) can skip an
    accumulator the same SIZE as the one it needs for nothing (2026-09-27:
    same fix OURS/PSEUDO's own copy of this function got earlier this
    session, after it OOM'd on a real whole-slide run purely from this
    unconditional half -- unconditional in THIS copy still, since no
    caller here had needed it yet).

    field/mag/overlap: same meaning as the reference (field=level0 crop
    px, mag=resize ratio label relative to native=40X). cell_um: fine-cell
    size in level0 px is derived from force_image_size//16 (ViT patch
    grid), same as the reference's maskclip/patch kind (no separate
    cls_own_grid path -- ROI never needs cls-mode pooled vectors)."""
    import openslide

    force_image_size = max(16, round(field * mag / 40.0 / 16.0) * 16)
    grid = force_image_size // 16
    native_px = field

    slide = openslide.OpenSlide(wsi_path)
    W, H = slide.level_dimensions[0]

    # Read from whichever pyramid level actually matches the target
    # downsample (native_px/force_image_size), not always level 0 -- see
    # _CropDataset's own docstring for why. NOT slide.get_best_level_for_
    # downsample(): its semantics require the level's own downsample to
    # not EXCEED the target, so a level whose real downsample is
    # 4.00007 (real Aperio pyramids are rarely exact powers of 2) gets
    # rejected for a target of exactly 4.0 and it silently falls back to
    # level 0 -- confirmed on this exact WSI, 2026-09-10 (wanted level 1,
    # got level 0, no I/O saved at all). Pick whichever level's downsample
    # is CLOSEST to the target instead -- being off by 0.002% is
    # irrelevant next to the resize that already happens regardless.
    target_ds = native_px / force_image_size
    read_level = min(range(slide.level_count),
                      key=lambda lv: abs(slide.level_downsamples[lv] - target_ds))
    level_ds = slide.level_downsamples[read_level]
    read_size = max(1, round(native_px / level_ds))
    print(f"[preprocess] target_ds={target_ds:.2f} -> read_level={read_level} "
          f"(actual_ds={level_ds:.2f}) read_size={read_size}", flush=True)

    tissue, ms = segment_tissue(slide, **(tissue_params or {}))
    print(f"[preprocess] tissue mask done, RSS={_rss_gb():.2f}GB", flush=True)

    step = field_step(field, overlap)
    coords = build_lattice_coords(W, H, native_px, step, tissue, ms)
    print(f"[preprocess] lattice built, n_coords={len(coords)}, RSS={_rss_gb():.2f}GB", flush=True)
    if not coords:
        return {"idx": np.array([], dtype=np.int64),
                "feat": np.zeros((0, 512), dtype=np.float16),
                "feat_patch": np.zeros((0, 768), dtype=np.float16),
                "Hg": 0, "Wg": 0, "cell_px": native_px / grid, "mpp_x": None}

    cell = native_px / grid   # level0 px per fine cell
    Hg = int(math.ceil(H / cell))
    Wg = int(math.ceil(W / cell))
    print(f"[preprocess] grid Hg={Hg} Wg={Wg} (Hg*Wg={Hg*Wg}) grid_eff={grid}", flush=True)

    coords_arr = np.array(coords, dtype=np.int64)
    cells, comp, ok = compact_cell_map(coords_arr, grid, cell, Hg, Wg)
    print(f"[preprocess] compact_cell_map done, n_cells={cells.size}, RSS={_rss_gb():.2f}GB", flush=True)

    # Accumulate ON DEVICE, not CPU -- the previous version moved each
    # batch's [B, grid*grid, 512] result to CPU and index_add_'d into a
    # CPU (n_cells, 512) tensor, 759 times over, for a 6.37M-row real WSI
    # accumulator. Measured (2026-09-10): t_wait(data)=3.5s vs
    # t_gpu(compute)=220s for the SAME run -- data loading was never the
    # bottleneck, the repeated CPU scatter-add (and the H2D/D2H shuffling
    # around it) was. comp/ok/cell_weight moved to device ONCE, sum_t/cnt_t
    # live on device throughout, only the final (much smaller, post-`keep`
    # filter) result is pulled to CPU/numpy at the very end.
    comp_dev = torch.from_numpy(comp).to(device)
    ok_dev = torch.from_numpy(ok).to(device)
    cell_weight = spline_weight_grid(grid).to(device)
    sum_t = torch.zeros(cells.size, 512, device=device)
    sum_t_patch = torch.zeros(cells.size, 768, device=device) if need_patch else None
    cnt_t = torch.zeros(cells.size, device=device)

    extractor = MaskclipExtractor(model, grid)
    loader = DataLoader(_CropDataset(wsi_path, coords, native_px, preprocess,
                                      read_level=read_level, read_size=read_size),
                         batch_size=batch_size, shuffle=False,
                         num_workers=num_workers, pin_memory=pin_memory)
    idx0 = 0
    n_batches = math.ceil(len(coords) / batch_size)
    # Split "waiting on the DataLoader" (CPU: openslide read_region + JPEG
    # decode + resize + collate, across num_workers processes) from
    # "compute" (H2D transfer + forward pass + on-device accumulation) --
    # without this split, a batch/worker-count tweak that changes
    # wall-clock time gives no way to tell whether it helped the real
    # bottleneck or made it worse.
    t_wait = 0.0
    t_compute = 0.0
    t_mark = time.time()
    for bi, (imgs, X, Y) in enumerate(loader):
        t_wait += time.time() - t_mark
        if bi % 20 == 0:
            gpu_alloc = torch.cuda.memory_allocated(device) / 1e9 if device.type == "cuda" else 0.0
            print(f"[preprocess] batch {bi}/{n_batches} RSS={_rss_gb():.2f}GB "
                  f"gpu_alloc={gpu_alloc:.2f}GB t_wait={t_wait:.1f}s t_compute={t_compute:.1f}s", flush=True)
        t0 = time.time()
        B = imgs.shape[0]
        imgs = imgs.to(device, non_blocking=True)
        raw, raw_patch = extractor(imgs)          # [B, grid*grid, 512] / [B, grid*grid, 768], on device
        comp_b = comp_dev[idx0:idx0 + B].reshape(-1)
        ok_b = ok_dev[idx0:idx0 + B].reshape(-1)
        idx0 += B
        raw_flat = raw.reshape(-1, raw.shape[-1]).float()
        comp_ok = comp_b[ok_b]
        wsel = cell_weight.repeat(B)[ok_b]
        sum_t.index_add_(0, comp_ok, raw_flat[ok_b] * wsel[:, None])
        if need_patch:
            raw_patch_flat = raw_patch.reshape(-1, raw_patch.shape[-1]).float()
            sum_t_patch.index_add_(0, comp_ok, raw_patch_flat[ok_b] * wsel[:, None])
        cnt_t.index_add_(0, comp_ok, wsel)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        t_compute += time.time() - t0
        t_mark = time.time()

    print(f"[preprocess] extraction loop done, RSS={_rss_gb():.2f}GB "
          f"t_wait(data)={t_wait:.1f}s t_compute={t_compute:.1f}s", flush=True)
    keep_t = cnt_t > 1e-6
    feat = (sum_t[keep_t] / cnt_t[keep_t].unsqueeze(1)).cpu().numpy()
    nrm = np.linalg.norm(feat, axis=1, keepdims=True)
    np.maximum(nrm, 1e-12, out=nrm)
    feat = (feat / nrm).astype(np.float16)

    # patch: same weighted-mean-then-L2-normalise treatment as maskclip's
    # `feat` above -- the reference's own on-disk cache keeps patch raw/
    # un-normalised (other consumers there want that literal magnitude),
    # but the vMF mixture this feeds into (utils/partition.py) assumes
    # unit-norm per channel same as any other channel, so it gets
    # normalised here rather than carried raw (see MaskclipExtractor).
    if need_patch:
        feat_patch = (sum_t_patch[keep_t] / cnt_t[keep_t].unsqueeze(1)).cpu().numpy()
        nrm_patch = np.linalg.norm(feat_patch, axis=1, keepdims=True)
        np.maximum(nrm_patch, 1e-12, out=nrm_patch)
        feat_patch = (feat_patch / nrm_patch).astype(np.float16)
    else:
        feat_patch = np.zeros((0, 768), dtype=np.float16)

    idx = cells[keep_t.cpu().numpy()]

    mpp_x = slide.properties.get("openslide.mpp-x")
    return {"idx": idx, "feat": feat, "feat_patch": feat_patch, "Hg": Hg, "Wg": Wg, "cell_px": cell,
            "mpp_x": float(mpp_x) if mpp_x else None}
