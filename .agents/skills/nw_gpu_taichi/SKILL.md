---
name: nw_gpu_taichi
description: Guidelines for adding Taichi GPU kernels to the NFP pipeline. Read before touching nfp_gpu_taichi.py, minkowski_engine.py, or minkowski_utils.py for GPU work.
---

# Skill: Taichi GPU Acceleration for NFP

> Read this before modifying `nfp_gpu_taichi.py`, `minkowski_engine.py`, or any GPU-related code.

## Files

| File | Role |
|------|------|
| `nestingworkbench/Tools/Nesting/algorithms/nfp_gpu_taichi.py` | All Taichi kernels live here |
| `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` | Dispatches CPU vs GPU, caches NFPs |
| `nestingworkbench/Tools/Nesting/algorithms/minkowski_utils.py` | CPU Minkowski-sum/IFP math (Shapely) |

---

## Current GPU Coverage (as of GPU-TODO work)

| Step | Acceleration |
|------|-------------|
| Convex vertex-sum (A_i + B_j) | ✅ GPU — `compute_nfp_pairs_kernel` |
| Convex hull of vertex-sum output | ❌ CPU — `MultiPoint().convex_hull` (Shapely) |
| Union of per-pair NFP hulls | ❌ CPU — `unary_union` (Shapely/GEOS) |
| Point-in-polygon (NFP collision test) | ✅ GPU — `is_inside_any_convex_kernel` |
| IFP for holes | ❌ CPU |
| Convex decomposition (triangulation) | ❌ CPU — Shapely `triangulate` |

---

## Architecture Constraints

### Taichi Kernel Rules
- **Only one `ti.init()` call per process.** It runs at module-import time in `nfp_gpu_taichi.py`. Never call `ti.init()` again inside functions.
- **Kernels compile on first call (JIT).** Expect a ~0.5–2s warm-up on first placement.
- **Ndarray arguments only for data exchange.** Pass numpy arrays as `ti.types.ndarray()` parameters; do not use Taichi fields for cross-kernel state.
- **All kernel calls must be protected by `_kernel_lock`** to prevent concurrent GPU launches from the background precompute pool.
- **No Shapely inside kernels.** All Shapely work must happen on CPU before or after kernel calls.
- **Kernels run from any thread** (lock is held), but `ti.init()` must have been called on the main thread first.

### Convex-Hull-on-GPU Rule
The existing `compute_nfp_pairs_kernel` outputs the raw vertex cloud `{A_i + B_j}`. The convex hull of that cloud is the Minkowski sum. **The convex hull step is currently done on CPU with Shapely.** A GPU convex hull kernel must:
1. Sort points by angle (or use gift-wrapping) — implement as a separate `@ti.kernel`.
2. Return the hull vertex indices (not all points) to minimise CPU↔GPU transfer.
3. Be called immediately after `compute_nfp_pairs_kernel` before data leaves GPU memory.

### Polygon-Union-on-GPU Rule
`unary_union` of many convex NFP hulls is the single largest CPU bottleneck. On GPU this requires a parallel polygon clipping algorithm (e.g. Sutherland-Hodgman). Key constraints:
- Max vertex count per polygon must be **statically bounded** for Taichi ndarray allocation.
- Use `POLY_MAX_VERTS = 64` as the allocation limit; larger polygons fall back to CPU.
- The union result is returned as a flat vertex array + length per polygon.

### Candidate Scoring Rule
`score_candidates_gpu` / `is_inside_any_convex_kernel` is already GPU-accelerated. Leave the API unchanged; only improve the kernel if vertex capacity needs increasing.

---

## Adding a New Kernel — Checklist

1. **Define the kernel** with `@ti.kernel` inside `if TAICHI_AVAILABLE:` block in `nfp_gpu_taichi.py`.
2. **Write a Python wrapper function** (no `@ti.kernel` decorator) immediately after the kernel, under the same `if TAICHI_AVAILABLE:` block. The wrapper handles numpy↔ndarray conversion and acquires `_kernel_lock`.
3. **Add a CPU stub** in the `else:` block at the bottom of the file that raises `ImportError`.
4. **Call from `minkowski_engine.py`** only — never call Taichi functions directly from `minkowski_utils.py` or `nesting_strategy.py`.
5. **Test with `use_gpu=False`** first to confirm correctness, then enable GPU.

---

## Performance Pattern: Batch First, Launch Once

The biggest GPU win comes from batching many pairs into a single kernel launch, not from GPU-ing each pair individually.

```python
# BAD: one kernel call per NFP pair
for pair in pairs:
    hulls.append(gpu_compute_nfp(pair))

# GOOD: all pairs in one kernel call
hulls = gpu_compute_nfp_batch(pairs)  # single kernel dispatch
```

Always accumulate all `(A, B, angle)` pairs before launching the kernel.

---

## Data Flow for GPU NFP

```
CPU: Convex decompose A and B  (cached in _decomp_cache)
CPU: Reflect B to get -B
CPU: Pack vertex arrays into numpy ndarrays
         ↓ _kernel_lock ↓
GPU: compute_nfp_pairs_kernel → raw vertex clouds per pair
         ↑ return ndarray ↑
CPU: convex_hull per pair  ← TARGET: move to GPU (GPU-003)
CPU: unary_union of hulls  ← TARGET: move to GPU (GPU-004)
CPU: Store result in Shape.nfp_cache
```

---

## Known Issues / Gotchas

- **Taichi warm-up:** First kernel call compiles SPIR-V. Print a message so users don't think it hung.
- **Vulkan max workgroup size:** Usually 256 or 1024. Don't exceed this in `ti.ndrange` inner dimension.
- **Empty polygon guard:** Always check `count < 3` before constructing hull geometry.
- **Thread safety:** `Shape.nfp_cache_lock` and `_kernel_lock` are separate. Always acquire `Shape.nfp_cache_lock` on CPU side; never inside a Taichi kernel.
- **Float32 precision:** Taichi ndarrays use float32. Coordinates > ~10,000mm may lose precision. NFP is computed in centered space (polygon translated to origin) so this is normally fine.
