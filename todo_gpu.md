# GPU Acceleration Tasks

> **Skill required:** Read `.agents/skills/nw_gpu_taichi/SKILL.md` before starting any task here.
> **Also read:** `.agents/skills/nw_nfp_algorithm/SKILL.md` for NFP concepts.
>
> Tasks are ordered by **impact**. Complete GPU-001 and GPU-002 before GPU-003+.

---

## Why the GPU Isn't Helping Yet

The current GPU code only accelerates the **vertex-addition step** (`A_i + B_j`). Everything downstream remains on CPU:

```
compute_nfp_pairs_kernel → raw vertex cloud   ← GPU ✅
MultiPoint().convex_hull                       ← CPU ❌  (called per pair)
unary_union(all_hulls)                         ← CPU ❌  (THE bottleneck)
```

`unary_union` from Shapely/GEOS is the single largest bottleneck in the entire nesting pipeline. It is called in the inner placement loop for every part × every rotation.

---

## GPU-001: GPU Convex Hull (Eliminate Per-Pair CPU Round-Trip)

| Field | Value |
|-------|-------|
| Complexity | Medium |
| File | `algorithms/nfp_gpu_taichi.py` |
| Depends on | — |

**Context**

After `compute_nfp_pairs_kernel` computes the raw vertex cloud `{A_i + B_j}`,
we return the data to CPU and call `MultiPoint(points).convex_hull` via Shapely.
For N pairs, this is N separate CPU calls. Moving the hull computation to GPU eliminates
the round-trip and keeps intermediate data on-device.

**What to do**

1. Add a new `@ti.kernel` named `convex_hull_2d_kernel` in `nfp_gpu_taichi.py` (inside `if TAICHI_AVAILABLE:`).
   - Use the **gift-wrapping (Jarvis march)** algorithm — it is the simplest to implement per-thread in Taichi.
   - Signature:
     ```python
     @ti.kernel
     def convex_hull_2d_kernel(
         n_pairs: int,
         points: ti.types.ndarray(),     # [n_pairs, max_pts, 2]  float32
         n_points: ti.types.ndarray(),   # [n_pairs]              int32
         hull_out: ti.types.ndarray(),   # [n_pairs, max_pts, 2]  float32
         hull_len: ti.types.ndarray(),   # [n_pairs]              int32
     ):
     ```
   - Parallelise over `n_pairs` (outer loop). Inner loop is serial Jarvis march for each pair's point cloud.
   - Limit max hull vertices to `MAX_HULL_VERTS = 128`.

2. Write a Python wrapper `compute_convex_hulls_gpu(points_np, n_points_np)` that:
   - Allocates `hull_out` and `hull_len` ndarrays.
   - Acquires `_kernel_lock`, calls `convex_hull_2d_kernel`, releases lock.
   - Returns a list of `Polygon` objects built from the hull output (still on CPU, but now one Shapely call for the whole batch vs N calls).

3. Update `compute_nfp_pairs()` in `nfp_gpu_taichi.py`:
   - After `compute_nfp_pairs_kernel`, pass `out_verts_np` and `out_len_np` to `compute_convex_hulls_gpu`.
   - Remove the existing per-pair `MultiPoint(points).convex_hull` loop.

**Acceptance criteria**

1. `compute_nfp_pairs()` no longer calls `MultiPoint` or any Shapely hull function.
2. Nesting output with `use_gpu=True` matches CPU output (same sheet count, parts placed).
3. GPU Compute usage visible in Task Manager when nesting 20+ parts.

---

## GPU-002: Batch the Full `minkowski_sum()` Pipeline Through GPU

| Field | Value |
|-------|-------|
| Complexity | Medium |
| File | `algorithms/minkowski_engine.py`, `algorithms/nfp_gpu_taichi.py` |
| Depends on | GPU-001 |

**Context**

`_calculate_and_cache_nfp_gpu` in `minkowski_engine.py` already collects all `(A_i, -B_j, angle)` pairs
and passes them to `compute_nfp_pairs()`. However for each NFP only one angle is passed.
`minkowski_utils.minkowski_sum()` — the CPU path — handles rotation inline.
The GPU path should rotate the B polygon vertices **inside the kernel** rather than rotating
them on CPU and passing pre-rotated vertices.

Currently in `_calculate_and_cache_nfp_gpu`:
```python
parts_b_reflected = [scale(p, xfact=-1.0, yfact=-1.0, origin=(0,0)) for p in poly_B_parts]
# rotation happens inside kernel via `rotations` parameter
```
This is correct. The issue is everything after `compute_nfp_pairs` still uses Shapely.

**What to do**

1. After `compute_nfp_pairs()` returns hull polygons (after GPU-001 is done), the `unary_union` call in `_calculate_and_cache_nfp_gpu` line ~306 is the next bottleneck:
   ```python
   nfp_exterior_poly = unary_union(valid_hulls)  # ← still CPU
   ```

2. For the **common case** (no holes, all hulls are convex, ≤ `POLY_MAX_VERTS=64` vertices each),
   replace `unary_union` with the GPU union kernel added in **GPU-003**.
   Fall back to `unary_union` when: any hull has more than 64 vertices, or `shape_A.original_polygon.interiors` is non-empty.

3. Log when the CPU fallback path is taken:
   ```python
   FreeCAD.Console.PrintLog("[MinkowskiEngine] GPU union fallback to CPU (complex polygon)\n")
   ```

**Acceptance criteria**

1. For parts without holes, `_calculate_and_cache_nfp_gpu` does not call `unary_union`.
2. For parts with holes, CPU fallback path is taken and logged.
3. No regression in nesting output correctness.

---

## GPU-003: GPU Polygon Union (The Main Bottleneck)

| Field | Value |
|-------|-------|
| Complexity | High |
| File | `algorithms/nfp_gpu_taichi.py`, `algorithms/minkowski_engine.py` |
| Depends on | GPU-001 |

**Context**

`unary_union` in Shapely runs GEOS polygon union serially on CPU. It is called:
- Once per `(part_A, part_B, angle)` NFP computation inside `_calculate_and_cache_nfp_gpu`
- Once per sheet update inside `get_global_nfp_for` (line ~119–123 of `minkowski_engine.py`)

For N placed parts and M rotation angles, the total union cost is O(N × M) per part being placed.
This is the dominant CPU cost.

**Approach: Incremental Convex-Polygon Union on GPU**

For our use case, all polygons being unioned are **convex** (they are convex hulls of Minkowski sums).
The union of a set of convex polygons is not generally convex — but we only need the
**exterior boundary** for NFP collision tests. A practical approximation that works for nesting:

Use a **conservative bounding union**: compute the convex hull of all hull vertices. This over-estimates
the forbidden area (more conservative placement) but is exact for simple part shapes and is O(1)
GPU kernel vs O(N²) GEOS ops.

A more exact approach — compute the exact union by polygon clipping (Sutherland-Hodgman) —
is addressed as a stretch goal within this task.

**What to do**

1. Add `union_convex_hulls_gpu(hull_polygons)` to `nfp_gpu_taichi.py`:
   - Packs all hull vertices into a flat ndarray.
   - Calls `convex_hull_2d_kernel` on the combined vertex set (reuse GPU-001 kernel).
   - Returns a single `Polygon` (the convex hull of all input hulls' vertices).
   - Constrained to `POLY_MAX_VERTS = 64` vertices per input hull; falls back to CPU if exceeded.

2. Call `union_convex_hulls_gpu` from `minkowski_engine._calculate_and_cache_nfp_gpu` in place of `unary_union(valid_hulls)`.

3. In `get_global_nfp_for` (line ~119, `minkowski_engine.py`), the incremental `entry['polygon'].union(batch_union)` call is also a CPU bottleneck. Add a secondary GPU path:
   - When `self.use_gpu` is True, accumulate `batch_union` polygons across the loop and call `union_convex_hulls_gpu` once at the end instead of per-part `unary_union` + `union`.

4. **Stretch goal:** Implement exact Sutherland-Hodgman polygon clipping as a Taichi kernel for cases where the convex-hull approximation causes visible placement gaps. Gate it behind a separate `use_exact_gpu_union` flag defaulting to `False`.

**Acceptance criteria**

1. `_calculate_and_cache_nfp_gpu` does not call `unary_union` for parts without holes.
2. `get_global_nfp_for` does not call `.union()` for each part when `use_gpu=True`.
3. With 20+ non-convex parts and 4 rotation steps, total nesting time decreases visibly.
4. No parts overlap in the output (correctness check — conservative union may leave more whitespace but must not cause overlaps).

---

## GPU-004: Wire Up `compute_nfp_batch` to the Placement Path

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `algorithms/nfp_gpu_taichi.py`, `algorithms/minkowski_engine.py` |
| Depends on | — |

**Context**

`compute_nfp_batch(poly_a_list, poly_b_list, rotations_deg)` in `nfp_gpu_taichi.py` already implements
a proper batched GPU kernel (`compute_minkowski_sum_convex_kernel`) that computes NFPs for
**multiple A polygons × multiple B polygons × multiple rotation angles** in a single dispatch.

It is **never called** from `minkowski_engine.py`. The engine instead calls `compute_nfp_pairs()`
one angle at a time inside `_calculate_and_cache_nfp_gpu` and `precompute_nfp_batch`.

**What to do**

1. In `minkowski_engine.precompute_nfp_batch()` (line ~156), replace the per-missing-pair loop that
   calls `compute_nfp_pairs()` with a single call to `compute_nfp_batch()`:
   - Collect all unique `(A, B)` pairs and all angles.
   - Call `nfp_gpu_taichi.compute_nfp_batch(poly_A_parts, poly_B_parts_reflected, angles_deg)`.
   - Map results back to cache keys using the rotation index.

2. The return format of `compute_nfp_batch` is `List[List[Polygon]]` — `results_per_rotation[r]` is
   the list of convex hull polygons for rotation `r`. Union them per rotation to get the full NFP.

3. Keep `_calculate_and_cache_nfp_gpu` (single-angle path) unchanged — it handles the cache-miss case
   during live placement when `precompute_nfp_batch` didn't cover that angle.

**Acceptance criteria**

1. `precompute_nfp_batch()` calls `compute_nfp_batch()` instead of the `compute_nfp_pairs()` loop.
2. Log the batch size on each call: `f"[MinkowskiEngine] GPU batch: {len(all_convex_pairs)} pairs"`.
3. No regression in NFP correctness (same shapes produced).

---

## GPU-005: GPU Candidate Point Scoring — Increase Vectorisation

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `algorithms/minkowski_engine.py`, `algorithms/nesting_strategy.py` |
| Depends on | — |

**Context**

`score_candidates_gpu()` in `minkowski_engine.py` already uses `is_inside_any_convex_kernel`
for PIP tests. However it still calls `bin_polygon.contains(test_poly)` via Shapely for bounds
checking (line ~253), running on CPU for every non-colliding candidate point.

**What to do**

1. Add a `bounds_check_kernel` to `nfp_gpu_taichi.py`:
   ```python
   @ti.kernel
   def bounds_check_kernel(
       n_pts: int,
       points: ti.types.ndarray(),          # [n_pts, 2]  float32 — candidate centroids
       rotated_extents: ti.types.ndarray(), # [n_pts, 4]  float32 — [min_x, min_y, max_x, max_y] per candidate
       bin_w: float,
       bin_h: float,
       results: ti.types.ndarray(),         # [n_pts]  int32 — 1=in-bounds, 0=out
   ):
   ```
   - For each point: check `0 <= pt.x + (min_x - cx) ... etc` against `bin_w/bin_h`.
   - This replaces the Shapely `contains` call for the common rectangular-bin case.

2. In `score_candidates_gpu()`, after the PIP test filters out NFP-colliding points:
   - Batch-compute `rotated_extents` for all remaining candidates on CPU (numpy, fast).
   - Call `bounds_check_kernel` for the batch.
   - Only call Shapely `contains` as a fallback for non-rectangular bins (currently unused).

3. The `_evaluate_rotation` CPU path (line ~110 in `nesting_strategy.py`) retains its existing
   Shapely bounds check. Only the GPU path in `score_candidates_gpu` changes.

**Acceptance criteria**

1. `score_candidates_gpu` does not call `bin_polygon.contains` in the hot loop.
2. Log at verbose level: `f"[MinkowskiEngine] GPU scored {n} candidates in batch"`.
3. No placement regression.

---

## GPU-006: Log GPU vs CPU Timing Per NFP Computation

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `algorithms/minkowski_engine.py` |
| Depends on | — |

**Context**

There is currently no way to tell how much time is spent in GPU vs CPU NFP computation.
This makes it impossible to measure speedup from GPU-001 through GPU-005.

**What to do**

1. In `_calculate_and_cache_nfp_gpu` and `_calculate_and_cache_nfp`, add timing around the
   expensive calls when `self.verbose` is True:
   ```python
   if self.verbose:
       t0 = time.perf_counter()
   hulls = nfp_gpu_taichi.compute_nfp_pairs(pairs)
   if self.verbose:
       self.log(f"GPU NFP pairs ({len(pairs)} pairs): {(time.perf_counter()-t0)*1000:.1f}ms")
   ```

2. Add the same timing around `unary_union` calls.

3. In `precompute_nfp_batch`, log total batch size and time:
   ```python
   self.log(f"GPU batch precompute: {len(missing_pairs)} NFPs in {elapsed:.1f}ms")
   ```

**Acceptance criteria**

1. With verbose logging enabled, the Report View shows per-NFP GPU and union timings.
2. No timing overhead when `verbose=False`.
