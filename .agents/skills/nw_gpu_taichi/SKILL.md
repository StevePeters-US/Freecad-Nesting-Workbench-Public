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

## Current GPU Coverage

| Step | Acceleration |
|------|-------------|
| Convex vertex-sum (A_i + B_j) | ✅ GPU — `compute_nfp_pairs_kernel` |
| Convex hull of vertex-sum output | ✅ GPU — `convex_hull_2d_kernel` / `compute_convex_hulls_gpu` |
| Union of per-pair NFP hulls (approx) | ✅ GPU — `union_convex_hulls_gpu` (conservative hull) |
| Point-in-polygon collision test | ✅ GPU — `is_inside_any_convex_kernel` / `compute_batch_pip_with_holes` |
| Bounds check (rectangular bin) | ✅ GPU — `bounds_check_kernel` |
| IFP for holes | ❌ CPU — `calculate_inner_fit_polygon` (Shapely) |
| Convex decomposition (triangulation) | ❌ CPU — Shapely `triangulate` |
| Exact polygon union | ❌ CPU — `unary_union` (Shapely/GEOS); GPU path avoids union entirely via No-Union scoring |

### No-Union GPU Scoring (GPU-007)

The GPU placement path avoids `unary_union` entirely for collision scoring. Instead of unioning all per-pair NFP hulls into one complex polygon (the "hot path" bottleneck), it stores them as individual pieces (`shells` and `holes`) and tests candidate points directly against the piece collection using a parallel Point-in-Polygon kernel.

**Data Structures:**
- **`shells`**: A list of convex polygons representing the solid forbidden area (Minkowski Sum pieces).
- **`holes`**: A list of convex polygons representing allowed regions inside placed parts (IFP for holes).

**Collision Logic (per-part, not global):**

**WRONG (causes overlapping parts inside holes):**
```
collision = (inside ANY shell from ALL parts) AND NOT (inside ANY hole from ALL parts)
```

**CORRECT:**
```
collision = ANY placed_part where (inside placed_part.shells AND NOT inside placed_part.holes)
```

A hole from part A only cancels a collision with A's shells — never with part B's shells.
Use `entry['per_part_nfps']` (one `{shells, holes}` dict per placed part) and OR results:
```python
rejected = np.zeros(n, dtype=np.int32)
for nfp_pair in entry['per_part_nfps']:
    if nfp_pair['holes']:
        r = compute_batch_pip_with_holes(pts, nfp_pair['shells'], nfp_pair['holes'])
    else:
        r = compute_batch_pip(pts, nfp_pair['shells'])
    rejected |= r
```

The flat `entry['shells']` and `entry['holes']` lists are used only for candidate point
discretization — not for collision scoring.

**Critical:** Both `precompute_nfp_batch` and `_calculate_and_cache_nfp_gpu` must write the same `shells`/`holes` format. See `todo_nfp.md` NFP-008 for the case where `precompute_nfp_batch` stores empty holes for parts with interior rings.

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
CPU: Convex decompose A and B (cached in _decomp_cache)
CPU: Reflect B to get -B
CPU: Pack vertex arrays into numpy ndarrays
         ↓ _kernel_lock ↓
GPU: compute_nfp_pairs_kernel → raw vertex clouds per pair
GPU: convex_hull_2d_kernel → convex hulls per pair
GPU: union_convex_hulls_gpu (optional) → conservative approx union
         ↑ return ndarray ↑
CPU: Store results (shells, holes, polygon) in Shape.nfp_cache
```

---

## Known Issues / Gotchas

- **Taichi warm-up:** First kernel call compiles SPIR-V. Print a message so users don't think it hung.
- **Vulkan max workgroup size:** Usually 256 or 1024. Don't exceed this in `ti.ndrange` inner dimension.
- **Empty polygon guard:** Always check `count < 3` before constructing hull geometry.
- **Thread safety:** `Shape.nfp_cache_lock` and `_kernel_lock` are separate. Always acquire `Shape.nfp_cache_lock` on CPU side; never inside a Taichi kernel.
- **Float32 precision:** Taichi ndarrays use float32. Coordinates > ~10,000mm may lose precision. NFP is computed in centered space (polygon translated to origin) so this is normally fine.
