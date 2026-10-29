"""
partition.py -- multi-channel vMF (von Mises-Fisher) mixture clustering,
ported from EXPERIMENTS/CLUSTER/Partition.py's VMFMixtureMultiChannel +
cluster_vmf_multichannel + surrounding_pool + lab2d_to_geojson_features.

EXPERIMENTS is a read-only nano5-maintained mirror on this machine (never
imported/edited in place) -- this is a fresh reimplementation for
PIPELINE/ROI, not a copy-paste. The clustering math itself was ALREADY
decoupled from disk caching in the reference (VMFMixtureMultiChannel.fit
takes plain numpy feature blocks, not a cache handle) -- the cache
dependency Partition.py has lives entirely upstream, in how it LOADS those
blocks (get_config_cache/load_compact_cache). ROI's utils/preprocess.py
produces those same blocks in memory instead; this file is unchanged math
either way.

surrounding_pool has both a CPU path (scipy, fine for small/synthetic
grids) and a GPU-chunked path (real WSI scale -- the CPU path OOMs on a
real WSI's full (Hg,Wg,D) grid, see that function's own comment).

Output: lab2d_to_geojson_features here takes an explicit `names` list
(cluster id -> "EPI"/"TUM"/...) instead of the reference's generic
"cluster_{k}" labels -- names/colors are supplied by utils/zeroshot.py's
per-cluster classification, not invented here.
"""
import math
import re

import numpy as np
import torch.nn.functional as F
import scipy.special as sps
import torch
from scipy.ndimage import find_objects as ndi_find_objects
from scipy.ndimage import label as ndi_label
from scipy.ndimage import uniform_filter

# Generic per-cluster-id palette for the raw "clustering" stage output
# (before any zero-shot classification names a cluster) -- cycles via
# k % len(PALETTE) for K > len(PALETTE), same convention the reference
# uses for its own cluster/zero-shot report panels.
PALETTE = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40),
    (148, 103, 189), (140, 86, 75), (227, 119, 194), (127, 127, 127),
    (188, 189, 34), (23, 190, 207), (174, 199, 232), (255, 187, 120),
    (152, 223, 138), (255, 152, 150), (197, 176, 213), (196, 156, 148),
]


# ── vMF mixture math (verbatim logic from CLUSTER/Partition.py) ────────────

def _banerjee_kappa_t(rbar, d, cap=1e5):
    r = rbar.clamp(1e-6, 1.0 - 1e-6)
    return (r * (d - r * r) / (1.0 - r * r)).clamp(1e-3, cap)


def _log_Cd(kappa, nu):
    k = kappa.detach().cpu().numpy().astype(np.float64)
    log_iv = np.log(np.maximum(sps.ive(nu, k), 1e-300)) + k
    logC = nu * np.log(np.maximum(k, 1e-12)) - (nu + 1.0) * np.log(2 * np.pi) - log_iv
    return torch.tensor(logC, device=kappa.device, dtype=torch.float32)


def _cat_chunk_norm(Xs, i, j):
    """Chunk-local concat-then-normalise, assembled `j-i` rows at a time
    (never the full-N concat) -- avoids the OOM the reference hit on a
    large multiscale-UNI WSI (see reference docstring for the incident)."""
    xb = torch.cat([X[i:j].float() for X in Xs], dim=1)
    return xb / xb.norm(dim=1, keepdim=True).clamp_min(1e-8)


def _spherical_kmeans(Xs, K, device, iters=15, seed=42, chunk=1_000_000):
    N = Xs[0].shape[0]
    D = sum(X.shape[1] for X in Xs)
    g = torch.Generator(device=Xs[0].device).manual_seed(seed)
    init_idx = torch.randperm(N, generator=g, device=Xs[0].device)[:K]
    C = torch.cat([X[init_idx].float() for X in Xs], dim=1)
    C = C / C.norm(dim=1, keepdim=True).clamp_min(1e-8)
    for _ in range(iters):
        a = torch.empty(N, dtype=torch.long, device=device)
        for i in range(0, N, chunk):
            j = min(i + chunk, N)
            a[i:j] = (_cat_chunk_norm(Xs, i, j) @ C.t()).argmax(1)
        newC = torch.zeros(K, D, device=device)
        cnt = torch.zeros(K, device=device)
        for i in range(0, N, chunk):
            j = min(i + chunk, N)
            xb = _cat_chunk_norm(Xs, i, j)
            ab = a[i:j]
            newC.index_add_(0, ab, xb)
            cnt.index_add_(0, ab, torch.ones_like(ab, dtype=torch.float32))
        empty = cnt == 0
        newC = newC / cnt.clamp_min(1.0).unsqueeze(1)
        if empty.any():
            newC[empty] = C[empty]
        C = newC / newC.norm(dim=1, keepdim=True).clamp_min(1e-8)
    return C


def sinkhorn_balanced_resp(log_r, target_marginal=None, epsilon=0.5, iters=3):
    """Entropy-regularised Sinkhorn-Knopp column-balanced E-step (SwAV/
    SeLa-style): pushes fit-time responsibility toward equal per-cluster
    mass so one dominant population can't swallow the softmax. Only ever
    applied to fit()'s internal responsibility, never to the final full-N
    labelling."""
    N, K = log_r.shape
    device = log_r.device
    log_row = torch.full((N,), -math.log(N), device=device)
    log_col = (torch.log(target_marginal.clamp_min(1e-12)) if target_marginal is not None
               else torch.full((K,), -math.log(K), device=device))
    scaled = (log_r - log_r.max(dim=1, keepdim=True).values) / epsilon
    f = torch.zeros(N, device=device)
    g = torch.zeros(K, device=device)
    for _ in range(iters):
        f = log_row - torch.logsumexp(scaled + g.unsqueeze(0), dim=1)
        g = log_col - torch.logsumexp(scaled + f.unsqueeze(1), dim=0)
    Q = torch.exp(scaled + f.unsqueeze(1) + g.unsqueeze(0))
    return Q / Q.sum(dim=1, keepdim=True).clamp_min(1e-30)


def pca_reduce(feat, pca_dim, sampling_frac=0.1, seed=42):
    """OPTIONAL per-channel dimensionality reduction, ported from
    EXPERIMENTS/CLUSTER/Partition.py's own pca_reduce (--pca_dim) -- fits
    on a random subsample of THIS channel's already-extracted per-cell
    rows (no extra CONCH forward pass needed), applies to every row,
    L2-renormalises. Returns [N,pca_dim] float32 unit vectors. Applied
    independently to each block BEFORE cluster_vmf_multichannel -- every
    channel keeps its own mean/kappa in the mixture either way, so
    reducing one channel's dimensionality doesn't need to touch any
    other's."""
    from sklearn.decomposition import PCA
    N, D = feat.shape
    take = max(1, round(N * sampling_frac))
    rng = np.random.default_rng(seed)
    fit_idx = rng.choice(N, min(take, N), replace=False) if N > take else np.arange(N)
    n = min(pca_dim, D, len(fit_idx))
    pca = PCA(n_components=n, random_state=seed).fit(feat[fit_idx])
    proj = pca.transform(feat)
    nrm = np.linalg.norm(proj, axis=1, keepdims=True)
    print(f"    [pca] fit on {len(fit_idx):,}/{N:,} cells -> {n} dims", flush=True)
    return (proj / np.where(nrm < 1e-8, 1.0, nrm)).astype(np.float32)


class VMFMixtureMultiChannel:
    """Multi-channel vMF mixture: one shared cluster label per cell,
    per-channel mean direction (mu) + concentration (kappa), joint
    log-density = sum over channels."""

    def __init__(self, K, device, dims, max_iter=100, tol=1e-4, seed=42,
                 balanced=True, sinkhorn_epsilon=0.5, sinkhorn_iters=3, chunk=None):
        self.K, self.device, self.dims = K, device, list(dims)
        self.nu = [d / 2.0 - 1.0 for d in self.dims]
        self.max_iter, self.tol, self.seed = max_iter, tol, seed
        self.balanced = balanced
        self.sinkhorn_epsilon, self.sinkhorn_iters = sinkhorn_epsilon, sinkhorn_iters
        self.qtype = torch.float16 if device.type == "cuda" else torch.float32
        self.mu = self.kappa = self.log_pi = None
        # 16384 (the reference's own default) was tuned to bound memory for
        # a LARGE K (the (chunk, K) intermediate is what actually needs
        # bounding) -- at our K in the single/low double digits, that
        # intermediate is trivial regardless of chunk size, so the small
        # default just means far more Python-loop/kernel-launch round trips
        # than necessary. Measured (2026-09-10, K=8, N=6.37M): 389 chunks x
        # up to 100 EM iterations ~= 39k small GPU calls, ~500s wall clock
        # for what should be a GPU-memory-cheap computation. 1M default
        # cuts that to ~7 chunks/iteration; still bounded (not a full N
        # single shot) so it stays safe if K or N grows a lot later.
        self._CHUNK = chunk or 1_000_000

    def _logresp(self, Xs, mu, kappa, log_pi, logC):
        N = Xs[0].shape[0]
        out = torch.empty(N, self.K, device=self.device)
        base = (log_pi + sum(logC)).unsqueeze(0)
        for i in range(0, N, self._CHUNK):
            j = min(i + self._CHUNK, N)
            acc = base.expand(j - i, -1).clone()
            for Xc, muc, kapc in zip(Xs, mu, kappa):
                xb = Xc[i:j].float()
                acc = acc + kapc.unsqueeze(0) * (xb @ muc.t())
            out[i:j] = acc
        return out

    def fit(self, blocks_np):
        Xs = [torch.tensor(b, dtype=self.qtype, device=self.device) for b in blocks_np]
        N = Xs[0].shape[0]
        Ccat = _spherical_kmeans(Xs, self.K, self.device, seed=self.seed)
        a = torch.empty(N, dtype=torch.long, device=self.device)
        for i in range(0, N, self._CHUNK):
            j = min(i + self._CHUNK, N)
            a[i:j] = (_cat_chunk_norm(Xs, i, j) @ Ccat.t()).argmax(1)

        Nk = torch.zeros(self.K, device=self.device)
        for i in range(0, N, self._CHUNK):
            ab = a[i:i + self._CHUNK]
            Nk.index_add_(0, ab, torch.ones_like(ab, dtype=torch.float32))
        Nk = Nk.clamp_min(1e-8)
        mu, kappa = [], []
        for Xc, d in zip(Xs, self.dims):
            S = torch.zeros(self.K, d, device=self.device)
            for i in range(0, N, self._CHUNK):
                xb = Xc[i:i + self._CHUNK].float()
                ab = a[i:i + self._CHUNK]
                S.index_add_(0, ab, xb)
            mu.append(S / S.norm(dim=1, keepdim=True).clamp_min(1e-8))
            kappa.append(_banerjee_kappa_t(S.norm(dim=1) / Nk, d))
        log_pi = torch.log((Nk / Nk.sum()).clamp_min(1e-8))

        prev = -float("inf")
        for _ in range(self.max_iter):
            logC = [_log_Cd(kappa[c], self.nu[c]) for c in range(len(Xs))]
            log_r = self._logresp(Xs, mu, kappa, log_pi, logC)
            ll = torch.logsumexp(log_r, dim=1).sum().item()
            if self.balanced:
                resp = sinkhorn_balanced_resp(log_r, epsilon=self.sinkhorn_epsilon,
                                               iters=self.sinkhorn_iters)
            else:
                resp = torch.softmax(log_r, dim=1)
            del log_r
            Nk = resp.sum(0).clamp_min(1e-8)
            mu, kappa = [], []
            for Xc, d in zip(Xs, self.dims):
                S = torch.zeros(self.K, d, device=self.device)
                for i in range(0, N, self._CHUNK):
                    S += resp[i:i + self._CHUNK].t() @ Xc[i:i + self._CHUNK].float()
                mu.append(S / S.norm(dim=1, keepdim=True).clamp_min(1e-8))
                kappa.append(_banerjee_kappa_t((S.norm(dim=1) / Nk).clamp(1e-6, 1 - 1e-6), d))
            del resp
            log_pi = torch.log((Nk / Nk.sum()).clamp_min(1e-8))
            if abs(ll - prev) < self.tol * max(1.0, abs(prev)):
                break
            prev = ll
        self.mu, self.kappa, self.log_pi = mu, kappa, log_pi
        return self

    def log_posteriors(self, blocks_np):
        Xs = [torch.tensor(b, dtype=self.qtype, device=self.device) for b in blocks_np]
        logC = [_log_Cd(self.kappa[c], self.nu[c]) for c in range(len(Xs))]
        lr = self._logresp(Xs, self.mu, self.kappa, self.log_pi, logC)
        lr = lr - torch.logsumexp(lr, dim=1, keepdim=True)
        return lr.cpu().numpy().astype(np.float32)


def cluster_vmf_multichannel(blocks, K, seed, device, fit_idx=None,
                              balanced=True, sinkhorn_epsilon=0.5, sinkhorn_iters=3):
    """blocks: list of (N,D_c) numpy arrays, one per channel (e.g. identity
    + surrounding). fit_idx: optional row-index subset to FIT on (all N
    rows still get labelled via one log_posteriors() pass afterward).
    Returns (labels[N] int, log_posteriors[N,K] float32)."""
    dims = [b.shape[1] for b in blocks]
    model = VMFMixtureMultiChannel(K, device, dims, seed=seed, balanced=balanced,
                                    sinkhorn_epsilon=sinkhorn_epsilon,
                                    sinkhorn_iters=sinkhorn_iters)
    fit_blocks = blocks if fit_idx is None else [b[fit_idx] for b in blocks]
    model.fit(fit_blocks)
    log_post = model.log_posteriors(blocks)
    labels = log_post.argmax(axis=1)
    return labels, log_post


# ── surrounding_pool ─────────────────────────────────────────────────────────
# CPU path (uniform_filter) OOM'd on a real WSI grid (Hg*Wg ~11.8M cells):
# several simultaneous (Hg,Wg,D) float32 temporaries at D=512 is ~24GB EACH.
# GPU path below is not an optional speed-up here, it's what makes this
# function able to run at all at real WSI scale -- ported from the
# reference's _surrounding_pool_gpu, chunked along D so GPU memory stays
# bounded regardless of grid size (see _adaptive_d_chunk).

def _adaptive_d_chunk(D, HW, mem_budget_gb=20.0, bytes_per_unit=45.0):
    """How many of D channels to process per GPU chunk, bounding peak GPU
    memory to mem_budget_gb regardless of grid size. bytes_per_unit is an
    empirically-calibrated per-(cell x channel) cost from the reference
    (includes allocator overhead, not just the raw tensor)."""
    budget_bytes = mem_budget_gb * 1e9
    d = int(budget_bytes / (bytes_per_unit * max(HW, 1)))
    return max(1, min(D, d))


def _surrounding_pool_gpu(mu_grid, valid_grid, Wg, Hg, radius, device,
                           d_chunk=None, mem_budget_gb=20.0):
    Hg, Wg = int(Hg), int(Wg)
    D = mu_grid.shape[1]
    if d_chunk is None:
        d_chunk = _adaptive_d_chunk(D, Hg * Wg, mem_budget_gb)
    win = 2 * radius + 1
    area = float(win * win)

    valid_np = np.asarray(valid_grid, np.float32).reshape(Hg, Wg)
    valid_t = torch.from_numpy(valid_np).to(device)
    valid_bchw = valid_t.unsqueeze(0).unsqueeze(0)
    win_cnt = (F.avg_pool2d(valid_bchw, win, stride=1, padding=radius,
                             count_include_pad=True) * area).reshape(Hg, Wg)
    cnt_excl_self = win_cnt - valid_t
    has_neighbours = cnt_excl_self > 1e-8
    denom = torch.where(has_neighbours, cnt_excl_self, torch.ones_like(cnt_excl_self))

    # float16 host buffer, one only -- filled per-chunk, never a float32
    # duplicate of the whole thing (that doubling was a real OOM cause in
    # the reference's own history, see its docstring).
    surrounding = np.empty((Hg * Wg, D), np.float16)
    for d0 in range(0, D, d_chunk):
        d1 = min(d0 + d_chunk, D)
        mu3 = torch.from_numpy(np.ascontiguousarray(mu_grid[:, d0:d1])).to(device) \
            .reshape(Hg, Wg, d1 - d0)
        masked = mu3 * valid_t.unsqueeze(-1)
        masked_bchw = masked.permute(2, 0, 1).unsqueeze(0)
        win_sum = (F.avg_pool2d(masked_bchw, win, stride=1, padding=radius,
                                 count_include_pad=True) * area)
        win_sum = win_sum.squeeze(0).permute(1, 2, 0)
        sum_excl_self = win_sum - masked
        mean_excl_self = sum_excl_self / denom.unsqueeze(-1)
        surrounding[:, d0:d1] = mean_excl_self.reshape(
            Hg * Wg, d1 - d0).to(torch.float16).cpu().numpy()

    nrm = np.linalg.norm(surrounding, axis=1, keepdims=True).astype(np.float32)
    np.maximum(nrm, np.float32(1e-12), out=nrm)
    np.divide(surrounding, nrm, out=surrounding)
    has_flat = has_neighbours.reshape(-1).cpu().numpy()
    surrounding[~has_flat] = 0.0
    return surrounding, has_flat


def surrounding_pool(mu_grid, valid_grid, Wg, Hg, radius, device=None, mem_budget_gb=20.0):
    """For every cell, the L2-normalised spherical mean of NEIGHBOURING
    valid cells' mu within a (2*radius+1)-side square window, excluding the
    cell itself and any invalid neighbours. Returns
    (surrounding[Hg*Wg,D] float16, has_neighbours[Hg*Wg] bool).

    device=a CUDA torch.device: GPU-chunked path (real WSI scale -- see
    module comment above). device=None or CPU: falls back to the
    scipy.ndimage path, fine for small/synthetic inputs, NOT for a real
    WSI's full grid."""
    if device is not None and device.type == "cuda":
        return _surrounding_pool_gpu(mu_grid, valid_grid, Wg, Hg, radius, device,
                                      mem_budget_gb=mem_budget_gb)

    Hg, Wg = int(Hg), int(Wg)
    D = mu_grid.shape[1]
    mu3 = np.asarray(mu_grid, np.float32).reshape(Hg, Wg, D)
    valid = np.asarray(valid_grid, np.float64).reshape(Hg, Wg)
    masked = mu3 * valid[:, :, None].astype(np.float32)

    win = 2 * radius + 1
    area = float(win * win)
    win_sum = uniform_filter(masked, size=(win, win, 1), mode="constant", cval=0.0) * np.float32(area)
    win_cnt = uniform_filter(valid, size=(win, win), mode="constant", cval=0.0) * area

    sum_excl_self = win_sum - masked
    cnt_excl_self = win_cnt - valid

    has_neighbours = cnt_excl_self > 1e-8
    denom = np.where(has_neighbours, cnt_excl_self, 1.0).astype(np.float32)
    mean_excl_self = sum_excl_self / denom[:, :, None]

    surrounding = mean_excl_self.reshape(Hg * Wg, D).astype(np.float32)
    nrm = np.linalg.norm(surrounding, axis=1, keepdims=True).astype(np.float32)
    np.maximum(nrm, np.float32(1e-12), out=nrm)
    np.divide(surrounding, nrm, out=surrounding)
    has_flat = has_neighbours.reshape(-1)
    surrounding[~has_flat] = 0.0
    return surrounding.astype(np.float16), has_flat


def knn_pool(feat, k=8, n_landmarks=20000, device=None, seed=42, chunk=8192):
    """SPIKE (2026-09-16, not wired into RegionProposal.py's run() yet) --
    a FEATURE-SPACE alternative to surrounding_pool's spatial neighbourhood
    average: for every cell, the L2-normalised mean of its k most
    cosine-similar OTHER cells in maskclip's own embedding space, instead
    of its k physically-adjacent cells. Purpose per user request 2026-09-16:
    inject more of CONCH's own pretrained (contrastively-learned, therefore
    already semantically structured) embedding geometry into clustering,
    WITHOUT any text prompt / fixed category vocabulary -- this channel
    never touches zeroshot.py's vocab JSONs at all, it only ever looks at
    feat itself.

    True brute-force N x N cosine similarity is infeasible at real-WSI N
    (up to ~1-2M cells -- N^2 blows GPU memory/time). Approximated via a
    fixed random LANDMARK subsample (Nystrom-style): every cell's top-k is
    chosen from among n_landmarks other cells, not the full N -- an N x M
    chunked matmul instead of N x N. Landmarks are excluded from their own
    top-k (a landmark cell's cosine similarity to ITSELF is trivially 1.0
    and would otherwise dominate its own pooled result, the same
    "excluding the cell itself" principle surrounding_pool already
    applies spatially).

    feat: (N,D) float32/float16, ALREADY L2-normalized (same convention as
    every other block in this module). Returns pooled[N,D] float16."""
    import torch
    N, D = feat.shape
    dev = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
    feat_t = torch.as_tensor(np.asarray(feat, np.float32), device=dev)

    g = torch.Generator(device="cpu").manual_seed(seed)
    m = min(n_landmarks, N)
    landmark_idx = torch.randperm(N, generator=g)[:m].to(dev)
    landmarks = feat_t[landmark_idx]                         # [M, D]

    pooled = torch.empty(N, D, device=dev, dtype=torch.float32)
    # landmark_pos[global cell id] = its column in `landmarks` if it IS one,
    # else -1 -- used to mask a landmark's own trivial self-match out of
    # its own top-k without an O(N*M) equality scan per chunk.
    landmark_pos = torch.full((N,), -1, dtype=torch.long, device=dev)
    landmark_pos[landmark_idx] = torch.arange(m, device=dev)

    kk = min(k, m - 1 if m > 1 else 1)
    for i0 in range(0, N, chunk):
        i1 = min(i0 + chunk, N)
        sim = feat_t[i0:i1] @ landmarks.t()                  # [chunk, M]
        rows = torch.arange(i0, i1, device=dev)
        self_col = landmark_pos[rows]
        has_self = self_col >= 0
        if has_self.any():
            sim[has_self, self_col[has_self]] = -2.0          # exclude self-as-landmark
        topv, topi = sim.topk(kk, dim=1)
        neigh = landmarks[topi]                                # [chunk, kk, D]
        pooled[i0:i1] = neigh.mean(dim=1)

    nrm = pooled.norm(dim=1, keepdim=True).clamp_min(1e-8)
    pooled = (pooled / nrm).to(torch.float16)
    return pooled.cpu().numpy()


# ── GeoJSON export ───────────────────────────────────────────────────────────

def slugify(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _grid_mask_to_outer_rings(mask):
    """mask: (H,W) bool grid of unit cells, ALREADY a single 4-connected
    component (caller's job -- see lab2d_to_geojson_features). Returns a
    list of rings (closed (x,y) grid-corner point lists) tracing the
    OUTER boundary of the region, via pure grid-edge topology -- NOT
    pixel/image contour tracing (cv2.findContours). Real WSI-adjacent
    issues this sidesteps entirely by construction, found/fixed
    2026-09-10 while patching cv2 one degenerate case at a time before
    switching to this:
      - a single isolated cell's cv2 contour collapses to ONE point (not
        its 4 corners) regardless of chain-approx mode or array padding --
        a fundamental property of cv2's border-following, not a
        configurable option; here a lone cell trivially contributes its
        own 4 edges like any other cell, no special case needed.
      - cv2's own connectivity is 8-connected (diagonal-touching regions
        get traced as one blob with a spurious thin "bridge" edge); the
        caller already enforces 4-connectivity via scipy.ndimage.label
        before calling this, so that mismatch cannot arise here at all.
      - every edge is exactly one cell side -> always axis-aligned, a
        diagonal line is not representable, let alone something the
        algorithm could accidentally produce.

    Algorithm: each "in" cell contributes an edge per side that borders
    an "out" cell (or the grid edge), oriented consistently (filled
    region on the walker's right) so edges chain into closed loops via
    shared endpoints. A true outer boundary and a hole's boundary end up
    with OPPOSITE net winding (shoelace sign): positive-area loops are
    this mask's outer silhouette(s), negative-area loops are real holes
    (some OTHER class's region enclosed inside this one -- e.g. stroma
    surrounding an epithelial island) and must be kept, not dropped: an
    earlier version dropped every negative-area ring on the mistaken
    assumption they were only ever same-class boundary noise (that noise
    is real but already eliminated upstream, by merging same-name cluster
    ids into one mask before labeling -- see lab2d_to_geojson_features).
    Dropping real holes left the surrounding class's polygon solid where
    it should have had the enclosed class's area cut out, so the two
    classes' polygons visibly overlapped (found 2026-09-11 via a shapely
    cross-class intersection check on real output: 18% of total polygon
    area was overlapping). Returned as (outer_rings, hole_rings) --
    caller assigns each hole to its containing outer ring.

    Collinear points along a straight run of cell edges are NOT merged by
    the edge-emission step (each cell side is its own point-pair) --
    merged in a cheap follow-up pass here, since a real region can easily
    be tens of cells across along one straight edge and un-merged points
    would bloat the geojson for no visual difference."""
    H, W = mask.shape

    def shifted_out(dr, dc):
        out = np.ones_like(mask, dtype=bool)
        r0, r1 = max(0, -dr), H - max(0, dr)
        c0, c1 = max(0, -dc), W - max(0, dc)
        out[r0:r1, c0:c1] = ~mask[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        return out

    top = mask & shifted_out(-1, 0)
    bottom = mask & shifted_out(1, 0)
    left = mask & shifted_out(0, -1)
    right = mask & shifted_out(0, 1)

    # direction index cycles 0(+x,"top")->1(+y,"right")->2(-x,"bottom")->
    # 3(-y,"left")->0, each step a 90 deg CLOCKWISE turn in (x-right,
    # y-down) image coords. A single vertex CAN have more than one
    # outgoing edge -- e.g. a large, winding/noisy connected component
    # that loops back and touches itself at one corner (real, confirmed
    # 2026-09-10 on real clustering output: a naive point->point dict let
    # the second edge silently overwrite the first, corrupting that
    # ring's chain, which then failed to close and got dropped whole --
    # measurable area loss, not just a cosmetic glitch). edges is a
    # per-point LIST of (next_point, direction), not a single value, so
    # no edge is ever silently lost to a dict-key collision.
    edges = {}
    for r, c in zip(*np.nonzero(top)):
        edges.setdefault((c, r), []).append(((c + 1, r), 0))
    for r, c in zip(*np.nonzero(right)):
        edges.setdefault((c + 1, r), []).append(((c + 1, r + 1), 1))
    for r, c in zip(*np.nonzero(bottom)):
        edges.setdefault((c + 1, r + 1), []).append(((c, r + 1), 2))
    for r, c in zip(*np.nonzero(left)):
        edges.setdefault((c, r + 1), []).append(((c, r), 3))

    def signed_area(ring):
        a = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            a += x0 * y1 - x1 * y0
        return a / 2.0

    def simplify_collinear(ring):
        out = [ring[0]]
        for p in ring[1:-1]:
            x0, y0 = out[-1]
            x1, y1 = p
            if len(out) >= 2:
                x_1, y_1 = out[-2]
                if (x1 - x_1) * (y0 - y_1) == (y1 - y_1) * (x0 - x_1):
                    out[-1] = p   # straight continuation -- replace, don't append
                    continue
            out.append(p)
        out.append(out[0])
        return out

    used = set()   # (point, direction) edges already consumed by some ring

    def pick_next(point, incoming_dir):
        """At `point`, choose which of its (possibly several) unused
        outgoing edges to take next, given we arrived via incoming_dir.
        Priority: sharpest right turn first, then straight, then left,
        then reverse -- the standard "keep the filled region on your
        right hand" wall-following rule, which is what makes the result
        a simple (non-self-crossing) loop per visit even when the vertex
        itself is revisited later from a different direction."""
        for turn in (1, 0, -1, 2):
            want_dir = (incoming_dir + turn) % 4
            for nxt, d in edges.get(point, []):
                if d == want_dir and (point, d) not in used:
                    return nxt, d
        return None

    n_edges_total = sum(len(v) for v in edges.values())
    outer_rings, hole_rings = [], []
    for start_point, start_edges in list(edges.items()):
        for start_next, start_dir in list(start_edges):
            if (start_point, start_dir) in used:
                continue
            used.add((start_point, start_dir))
            ring = [start_point]
            cur_point, cur_dir = start_next, start_dir
            ok = True
            for _ in range(n_edges_total + 1):
                ring.append(cur_point)
                if cur_point == start_point:
                    break
                nxt = pick_next(cur_point, cur_dir)
                if nxt is None:
                    ok = False
                    break
                nxt_point, nxt_dir = nxt
                used.add((cur_point, nxt_dir))
                cur_point, cur_dir = nxt_point, nxt_dir
            else:
                ok = False
            if not ok or ring[-1] != start_point:
                continue   # malformed chain -- skip rather than emit bad geometry
            (outer_rings if signed_area(ring) > 0 else hole_rings).append(simplify_collinear(ring))
    return outer_rings, hole_rings


def lab2d_to_geojson_features(lab2d, K, cell_f, names, colors, drop_holes=False):
    """Convert a (Hg,Wg) int32 cluster-label grid (-1 = invalid) into a
    list of GeoJSON Polygon Features, one per disjoint same-CLASS
    connected component, scaled from grid cell units to level0 pixel
    space via cell_f. Boundary tracing is pure grid-edge topology (see
    _grid_mask_to_outer_rings). Holes (another class's region enclosed
    inside this one) are kept as interior rings by default, not dropped
    -- dropping them made the enclosing class's polygon solid over the
    enclosed class's area too, i.e. two different classes' polygons
    genuinely overlapping (found 2026-09-11, see _grid_mask_to_outer_rings).

    drop_holes=True (2026-09-16, proposal-stage-only per user request):
    a hole is only kept when something INSIDE it is itself a kept
    proposal cluster (names[k] is not None); a hole whose enclosed area
    is entirely non-proposal content is absorbed into the solid fill
    instead -- for a region PROPOSAL (as opposed to clustering/
    zeroshot's own precise per-cluster QA geometry), a small pocket of
    some non-proposal cluster inside an otherwise-kept blob doesn't need
    its own hole; the outer boundary already covers it ("外框會包起來").
    A hole enclosing ANOTHER kept proposal cluster is a different case
    and is NOT dropped: two different proposal classes nested inside
    each other (found 2026-09-16 on real BCSS output -- a "tumor" blob
    fully surrounding a smaller "dcis"/"normal_acinus_or_duct" region,
    both legitimately kept once BCSS's proposal set grew past
    BRACS/CRC's original EPI+TUM pair) must stay two genuinely separate
    shapes, or the outer one visually swallows the inner one even though
    Viewer.py draws them in the same single filled layer.

    Grouped by classification NAME, not by raw cluster id (real bug, found
    2026-09-10: two different cluster ids can both classify as "EPI" and
    sit spatially adjacent -- masking/contouring per cluster id drew a
    meaningless boundary line between two touching regions that render
    identically, since the viewer only ever shows the name/color, not the
    underlying cluster id). Cluster ids sharing a name are merged into ONE
    mask, so touching same-class regions become a single connected
    component with no spurious internal edge.

    names/colors: length-K lists, cluster id k -> classification name
    (e.g. "EPI"/"TUM", None if excluded) / RGB color tuple -- supplied by
    utils/zeroshot.py's per-cluster classification (this function doesn't
    invent labels). Cluster ids sharing a name are assumed to share a
    color too (true by construction in zeroshot.py: color is assigned
    purely from name).
    """
    name_to_ks = {}
    for k in range(K):
        if names[k] is not None:
            name_to_ks.setdefault(names[k], []).append(k)

    # 4-connectivity, not cv2's implicit 8-connectivity: two cells that
    # only touch at a corner have no real shared edge on a square-cell
    # grid. Splitting them into separate components BEFORE boundary
    # tracing is what makes a diagonal-only "bridge" between two
    # same-class blobs impossible (real user-reported artifact,
    # 2026-09-10) -- a correct connectivity DEFINITION, not
    # post-processing that erodes or otherwise changes which cells belong
    # to which class (morphological opening was tried and rejected: it
    # silently deletes any real region smaller than the structuring
    # element, changing the algorithm's actual output, not just how it's
    # drawn).
    _STRUCT_4CONN = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)

    def _point_in_ring(pt, ring):
        # standard ray-casting point-in-polygon test, ring closed (first
        # == last point) -- used only to route a hole to its containing
        # outer ring when a single 4-connected component's boundary
        # traces to more than one outer lobe (a pinch-point component,
        # see _grid_mask_to_outer_rings; rare, but a hole must still land
        # in the right lobe when it happens).
        x, y = pt
        inside = False
        n = len(ring) - 1
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y):
                x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < x_at_y:
                    inside = not inside
            j = i
        return inside

    features = []
    for name, ks in name_to_ks.items():
        mask = np.isin(lab2d, ks)
        if not mask.any():
            continue
        labeled, n_components = ndi_label(mask, structure=_STRUCT_4CONN)
        r, g, b = colors[ks[0]]

        # find_objects gives each component's own bounding-box slice in
        # ONE vectorized pass -- cropping to it before boundary tracing
        # matters a lot here: most components are tiny (a handful of
        # cells) against a canvas that can be millions of cells, and
        # _grid_mask_to_outer_rings' shifted_out() was doing 4 full-canvas
        # numpy passes PER COMPONENT regardless of that component's real
        # size (measured 2026-09-10: this dwarfed the actual boundary-
        # tracing cost once single-cell components stopped being dropped
        # and n_components hit the tens of thousands on a real WSI).
        # Padded by 1 cell on each side so a component touching its own
        # bbox edge still gets a correct "out" neighbour to compare
        # against instead of relying on shifted_out's own off-grid
        # handling every time.
        for comp_id, sl in enumerate(ndi_find_objects(labeled), start=1):
            if sl is None:
                continue
            r0, r1 = max(0, sl[0].start - 1), min(labeled.shape[0], sl[0].stop + 1)
            c0, c1 = max(0, sl[1].start - 1), min(labeled.shape[1], sl[1].stop + 1)
            comp_mask = labeled[r0:r1, c0:c1] == comp_id
            outer_rings, hole_rings = _grid_mask_to_outer_rings(comp_mask)
            if not outer_rings:
                continue

            # A component normally has exactly one outer ring; a
            # pinch-point component (see _grid_mask_to_outer_rings) can
            # have several. Route each hole to whichever outer ring
            # actually contains it -- one point-in-ring test per
            # (hole, outer) pair, cheap since both counts are small per
            # component (this is not the millions-of-cells full-canvas
            # cost the bbox-cropping fix above addressed).
            holes_by_outer = [[] for _ in outer_rings]
            if not drop_holes:
                for hole in hole_rings:
                    for oi, outer in enumerate(outer_rings):
                        if _point_in_ring(hole[0], outer):
                            holes_by_outer[oi].append(hole)
                            break
                    # no containing outer ring found: drop this hole rather
                    # than guess -- should not happen, but a dropped hole is
                    # a far smaller error than a misassigned one.
            elif hole_rings:
                # Which of this component's holes enclose a KEPT proposal
                # cluster (see docstring) -- identified via the false-region
                # (comp_mask==False) connected components rather than the
                # hole_rings geometry directly, since that's where the
                # original cluster ids (lab2d, not just this outer mask)
                # are still available. A false-component touching the
                # padded crop's own border is the shape's EXTERIOR, not an
                # enclosed hole (the 1-cell pad around comp_mask guarantees
                # the border is always background) -- only interior
                # (non-border) false-components are real holes.
                lab2d_crop = lab2d[r0:r1, c0:c1]
                false_labeled, n_false = ndi_label(~comp_mask, structure=_STRUCT_4CONN)
                border_ids = (set(np.unique(false_labeled[0, :])) | set(np.unique(false_labeled[-1, :]))
                              | set(np.unique(false_labeled[:, 0])) | set(np.unique(false_labeled[:, -1])))
                border_ids.discard(0)
                for fid in range(1, n_false + 1):
                    if fid in border_ids:
                        continue
                    hole_cells = false_labeled == fid
                    hole_cluster_ids = np.unique(lab2d_crop[hole_cells])
                    if not any(cid >= 0 and names[cid] is not None for cid in hole_cluster_ids):
                        continue   # every cluster inside is non-proposal -- absorb into the solid fill
                    ry, rx = np.argwhere(hole_cells)[0]
                    probe = (rx + 0.5, ry + 0.5)   # strictly inside one of this hole's own cells
                    matched_hole = next((h for h in hole_rings if _point_in_ring(probe, h)), None)
                    if matched_hole is None:
                        continue
                    for oi, outer in enumerate(outer_rings):
                        if _point_in_ring(matched_hole[0], outer):
                            holes_by_outer[oi].append(matched_hole)
                            break

            for oi, outer_pts in enumerate(outer_rings):
                ring = [[float(x + c0) * cell_f, float(y + r0) * cell_f] for x, y in outer_pts]
                holes = [[[float(x + c0) * cell_f, float(y + r0) * cell_f] for x, y in h]
                         for h in holes_by_outer[oi]]
                xs = [p[0] for p in ring[:-1]]
                ys = [p[1] for p in ring[:-1]]
                bbox = [min(xs), min(ys), max(xs), max(ys)]   # same convention as DATASET/Convert.py
                features.append({
                    "type": "Feature",
                    "properties": {"classification": {"name": name,
                                                        "color": [int(r), int(g), int(b)]},
                                   "bbox": bbox},
                    "geometry": {"type": "Polygon", "coordinates": [ring] + holes},
                })
    return features
