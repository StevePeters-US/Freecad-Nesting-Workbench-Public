# NFP Hole Collision Tasks

> **Skills required:** Read `.agents/skills/nw_nfp_algorithm/SKILL.md` and `.agents/skills/nw_gpu_taichi/SKILL.md` before starting any task here.

---

## Root Cause: Mixed Shell/Hole Accumulation

The GPU No-Union scoring path accumulates all placed parts' NFP shells into one flat list
and all IFP hole pieces into another flat list. The collision test is:

```
collision = (inside ANY shell) AND NOT (inside ANY hole)
```

This is **semantically wrong** when multiple placed parts are on the sheet. A hole belonging
to placed part A should only cancel a collision with A's shells — it must never cancel a
collision with part B's shells.

**Failure scenario** (causes overlaps in the screenshot):

```
Placed: A (donut with hole), C (solid, already placed inside A's hole)
Placing: D

sheet.nfp_cache shells = [A_shells, C_shells]
sheet.nfp_cache holes  = [A_hole_IFP]

Candidate point P (inside A's hole AND inside C's shells):
  inside_any_shell = True   (P overlaps C — real collision)
  inside_any_hole  = True   (P is in A's hole)
  current result   = NOT colliding   ← WRONG: D would overlap C
  correct result   = colliding        ← must be rejected
```

The hole of A must only cancel the shell of A, not the shell of C.

---

## NFP-010: Fix TopologyException in `precompute_nfp_batch`

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | — |
| Priority | **HIGH — blocks pre-caching entirely when it fires** |

**Context**

`precompute_nfp_batch` (line ~277) calls `unary_union(hulls)` on raw convex hull polygons
produced by the GPU. These polygons have floating-point imprecision that GEOS rejects:

```
TopologyException: side location conflict at -70.850936889648438 126.79415130615234
```

`_calculate_and_cache_nfp_gpu` already handles this correctly with a small buffer:
```python
hulls_buffered = [h.buffer(1e-7) for h in valid_hulls]
nfp_exterior_poly = unary_union(hulls_buffered)
```

`precompute_nfp_batch` does not buffer before the CPU fallback union (line ~277).

The exception propagates to the outer `except Exception` at line ~296, which catches
the **entire batch** — aborting all pre-caching for every part in the batch. With zero
pre-cached NFPs, every placement falls back to on-demand computation, turning a fast
batch GPU run into sequential per-part GPU calls. This is the primary cause of the
231-second nesting time.

**What to do**

1. At line ~277, replace:
   ```python
   union_poly = unary_union(hulls)
   ```
   with:
   ```python
   union_poly = unary_union([h.buffer(1e-7) for h in hulls])
   ```

2. After the union, keep the existing validity check:
   ```python
   if not union_poly.is_valid:
       union_poly = union_poly.buffer(0)
   ```

**Acceptance criteria**

1. Nesting log no longer shows `Batch NFP precompute error: TopologyException`.
2. With 39 complex parts, `Shape.nfp_cache` is populated before the first placement begins.
3. Total nesting time drops significantly (from ~230s toward the expected ~20-40s range).

---

## NFP-011: Per-Pair Error Isolation in `precompute_nfp_batch`

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | — |
| Priority | HIGH — defense-in-depth after NFP-010 |

**Context**

Even after NFP-010, a single bad polygon pair can abort the entire batch. The outer
`try/except` at line ~224 wraps the whole function body. If any per-pair operation
raises an exception, all subsequent pairs in the batch are skipped.

**What to do**

Move the per-pair union and cache-write into its own `try/except`:

```python
for m_pair in m_pairs:
    angle = m_pair['angle_B']
    cache_key = m_pair['key']
    hulls = angle_to_results.get(angle, [])

    if not hulls:
        continue

    try:
        t_u0 = time.perf_counter()
        union_poly = nfp_gpu_taichi.union_convex_hulls_gpu(hulls)
        if union_poly is None:
            if self.verbose:
                FreeCAD.Console.PrintLog("[MinkowskiEngine] GPU batch union fallback to CPU\n")
            union_poly = unary_union([h.buffer(1e-7) for h in hulls])
        t_union += (time.perf_counter() - t_u0) * 1000

        if not union_poly.is_valid:
            union_poly = union_poly.buffer(0)

        nfp_data = {
            'shells': hulls,
            'holes': [],
            'polygon': union_poly,
            'points': [],
            'error': None
        }
        with Shape.nfp_cache_lock:
            if cache_key not in Shape.nfp_cache:
                Shape.nfp_cache[cache_key] = nfp_data

    except Exception as pair_err:
        self.log(f"Skipping pair {cache_key}: {pair_err}")
        # Individual pair failure — continue with remaining pairs
```

Keep the outer `try/except` around the GPU kernel dispatch (lines ~224–260) since a
kernel failure is unrecoverable for the whole batch.

**Acceptance criteria**

1. A single bad pair logs a warning but does not prevent other pairs from being cached.
2. When one pair fails, the remaining `N-1` pairs in the batch are still cached correctly.
3. No silent swallowing of exceptions — each failure is logged with the cache key.

---

## NFP-012: Fast-Path in NFP-007 When No Placed Part Has Holes

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | NFP-006, NFP-007 |
| Priority | HIGH — NFP-007 as written makes N GPU kernel calls per placement |

**Context**

NFP-007 introduces a per-part loop in `score_candidates_gpu` that makes one GPU kernel
call per placed part. With 39 placed parts this is 39 kernel calls per rotation angle.
GPU kernel dispatch has fixed overhead (~0.1–1ms each), so 39 calls × 4 rotations =
156 kernel calls per part placement. For 39 parts this is ~6,000 kernel calls total.

The vast majority of parts have no holes. For those cases, the per-part loop is
unnecessary — all shells can be tested in a single combined call.

**What to do**

In `score_candidates_gpu`, after getting `per_part`:

```python
per_part = nfp_entry.get('per_part_nfps', [])

if not per_part:
    results = np.zeros(len(points), dtype=np.int32)
elif not any(p['holes'] for p in per_part):
    # Fast path: no placed part has holes — single combined PIP call
    all_shells = [s for p in per_part for s in p['shells']]
    results = nfp_gpu_taichi.compute_batch_pip(pts_np, all_shells) if all_shells else np.zeros(len(points), dtype=np.int32)
else:
    # Slow path: at least one part has holes — must test per-part
    # Batch all no-hole parts together for one call, then add hole-parts individually
    rejected = np.zeros(len(points), dtype=np.int32)

    no_hole_shells = [s for p in per_part if not p['holes'] for s in p['shells']]
    if no_hole_shells:
        rejected |= nfp_gpu_taichi.compute_batch_pip(pts_np, no_hole_shells)

    for nfp_pair in per_part:
        if not nfp_pair['holes']:
            continue  # already handled above
        if nfp_pair['shells']:
            rejected |= nfp_gpu_taichi.compute_batch_pip_with_holes(
                pts_np, nfp_pair['shells'], nfp_pair['holes']
            )
    results = rejected
```

This reduces the common case (no holes anywhere on the sheet) to 1 kernel call, and
the hole case to 1 + N_hole_parts calls (typically 1 + 1 or 1 + 2).

**Acceptance criteria**

1. With no holed parts on the sheet, exactly 1 GPU PIP kernel call per rotation angle.
2. With 1 donut and N solid parts, exactly 2 kernel calls (1 for solids, 1 for donut).
3. No regression in collision correctness (overlapping parts still rejected).
4. Total nesting time for 39 parts should not regress vs. pre-NFP-007 baseline.

---

## NFP-006: Per-Part NFP Pairs — Sheet Cache Restructure

| Field | Value |
|-------|-------|
| Complexity | Medium |
| Files | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | — |

**Context**

`get_global_nfp_for` builds the sheet-level cache entry. Currently it appends translated
shells and holes into flat lists. Change it to record **one (shells, holes) pair per placed part**
so that collision can be tested per-part.

**What to do**

1. Add `'per_part_nfps': []` to the initial entry dict in `get_global_nfp_for` (line ~67):

```python
sheet.nfp_cache[cache_key] = {
    'polygon': Polygon(),
    'last_part_idx': 0,
    'points': [],
    'prepared': None,
    'shells': [],        # kept for backward compat / CPU path
    'holes': [],         # kept for backward compat / CPU path
    'per_part_nfps': [], # GPU path: list of {'shells': [...], 'holes': [...]}
}
```

2. In the GPU branch of the `for p in parts_to_process` loop (line ~121), replace the
   flat-list extension with a per-part dict append:

```python
if self.use_gpu:
    part_shells = []
    for piece in nfp_data.get('shells', []):
        rotated = rotate(piece, placed_angle, origin=(0, 0))
        part_shells.append(translate(rotated, xoff=cent.x, yoff=cent.y))

    part_holes = []
    for piece in nfp_data.get('holes', []):
        rotated = rotate(piece, placed_angle, origin=(0, 0))
        part_holes.append(translate(rotated, xoff=cent.x, yoff=cent.y))

    entry['per_part_nfps'].append({'shells': part_shells, 'holes': part_holes})

    # Keep flat shells for candidate-point discretization (points still needed)
    entry['shells'].extend(part_shells)
    entry['holes'].extend(part_holes)

    # Candidate points: discretize NFP boundary
    master = nfp_data.get('polygon')
    if master and not master.is_empty:
        rotated_m = rotate(master, placed_angle, origin=(0, 0))
        translated_m = translate(rotated_m, xoff=cent.x, yoff=cent.y)
        new_points.extend(self._discretize_edge(translated_m.exterior))
        for interior in translated_m.interiors:
            new_points.extend(self._discretize_edge(interior))
    else:
        for piece in part_shells:
            new_points.extend(self._discretize_edge(piece.exterior))
```

3. Append `'per_part_nfps': []` handling for the lock section at the bottom — `per_part_nfps`
   is already extended in-place above, so only `last_part_idx` and `points` need the lock
   update (no change to existing lock section structure needed).

**Acceptance criteria**

1. `sheet.nfp_cache[key]['per_part_nfps']` has one entry per placed part after `get_global_nfp_for`.
2. Each entry has `'shells'` (list of Polygons) and `'holes'` (list of Polygons, may be empty).
3. `entry['shells']` still contains all shells (flat, for discretization).
4. No regression in CPU-path nesting (CPU path does not use `per_part_nfps`).

---

## NFP-007: Per-Part Collision Evaluation in `score_candidates_gpu`

| Field | Value |
|-------|-------|
| Complexity | Medium |
| Files | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | NFP-006 |

**Context**

`score_candidates_gpu` currently calls `compute_batch_pip_with_holes(pts, shells, holes)`
once using the flat accumulated lists. Replace this with a per-part loop: a candidate point
is **rejected** if it collides with ANY placed part (i.e., inside that part's shells AND
NOT inside that part's holes).

**What to do**

Replace lines ~311–315 in `score_candidates_gpu`:

```python
# OLD — incorrect mixed shells/holes test
shell_pieces = nfp_entry.get('shells', [])
hole_pieces = nfp_entry.get('holes', [])
pts_np = np.array([[p.x, p.y] for p in points], dtype=np.float32)
if shell_pieces:
    results = nfp_gpu_taichi.compute_batch_pip_with_holes(pts_np, shell_pieces, hole_pieces)
else:
    results = np.zeros(len(points), dtype=np.int32)
```

with:

```python
# NEW — per-part collision evaluation
pts_np = np.array([[p.x, p.y] for p in points], dtype=np.float32)
per_part = nfp_entry.get('per_part_nfps', [])

if not per_part:
    # Empty sheet — no collision possible
    results = np.zeros(len(points), dtype=np.int32)
else:
    # A candidate is rejected if it collides with ANY placed part.
    # Collision with part i = inside part_i.shells AND NOT inside part_i.holes
    rejected = np.zeros(len(points), dtype=np.int32)
    for nfp_pair in per_part:
        p_shells = nfp_pair['shells']
        p_holes = nfp_pair['holes']
        if not p_shells:
            continue
        if p_holes:
            part_result = nfp_gpu_taichi.compute_batch_pip_with_holes(
                pts_np, p_shells, p_holes
            )
        else:
            part_result = nfp_gpu_taichi.compute_batch_pip(pts_np, p_shells)
        rejected |= part_result
    results = rejected
```

**Acceptance criteria**

1. A part placed inside donut A's hole cannot overlap another part C also inside A's hole.
2. A part can still be validly placed inside an empty donut hole (IFP works).
3. GPU kernel call count = number of placed parts with holes, not 1 total.
4. With zero placed parts with holes, only 1 kernel call is made (shells-only path).
5. Screenshot shows no overlapping parts when filling holes.

---

## NFP-008: Skip Flat Holes from `precompute_nfp_batch` in Hole Check

| Field | Value |
|-------|-------|
| Complexity | Low |
| Files | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | NFP-006, NFP-007 |

**Context**

`precompute_nfp_batch` stores `'holes': []` in pairwise cache entries (IFP for holes is not
computed in the batch path — only in `_calculate_and_cache_nfp_gpu`). When `get_global_nfp_for`
reads a batch-cached entry for a placed part that HAS holes, the holes list is empty. This
means the part's hole IFP is silently missing, so parts cannot be placed inside that hole.

The fix: when `get_global_nfp_for` reads a batch-cached entry with `holes: []` for a shape
that has interior rings (`shape_A.original_polygon.interiors`), fall through to
`_calculate_and_cache_nfp_gpu` to recompute the full entry with correct hole data.

**What to do**

In `get_global_nfp_for` (line ~102), after reading `nfp_data` from `Shape.nfp_cache`, add
a check:

```python
with Shape.nfp_cache_lock:
    nfp_data = Shape.nfp_cache.get(nfp_cache_key)

# If cached entry is missing holes for a part that has interior rings, recompute
if (nfp_data is not None
        and self.use_gpu
        and not nfp_data.get('holes')
        and p.shape.original_polygon
        and list(p.shape.original_polygon.interiors)):
    nfp_data = None  # force recompute via _calculate_and_cache_nfp_gpu

if not nfp_data:
    if self.use_gpu:
        nfp_data = self._calculate_and_cache_nfp_gpu(...)
    else:
        nfp_data = self._calculate_and_cache_nfp(...)
```

**Acceptance criteria**

1. After placing a donut, parts placed afterwards correctly receive IFP hole data in their
   per-part NFP entry.
2. `precompute_nfp_batch` results are still used for parts without interior rings (no recompute).
3. Parts can be placed inside holes when they fit.

---

## NFP-009: Add Regression Test for Hole-Filling Without Overlap

| Field | Value |
|-------|-------|
| Complexity | Low |
| File | `tests/test_gpu_holes.py` |
| Depends on | NFP-006, NFP-007 |

**Context**

There is no test that places TWO parts inside a hole and checks that they do not overlap
each other. This is the exact scenario shown in the screenshot.

**What to do**

Add `test_two_parts_in_hole_no_overlap` to `tests/test_gpu_holes.py`:

1. Create a large donut (`outer_r=10`, `inner_r=6`) as placed part A.
2. Place a small square (side=2) as part C at a known position inside A's hole.
3. Add both A and C to the sheet (`sheet.parts`).
4. Call `get_global_nfp_for(small_square_2, 0.0, sheet)` for a second small square D.
5. Assert that no candidate point that would place D overlapping C passes the collision test.
6. Assert that a candidate point well clear of C (but still inside A's hole) is valid.

Skip the test when `nfp_gpu_taichi.is_available()` returns False.

**Acceptance criteria**

1. Test passes with `use_gpu=True`.
2. Confirms that `rejected` array correctly marks C-overlapping candidates as 1.
3. Confirms that non-C-overlapping candidates inside A's hole are marked as 0.
