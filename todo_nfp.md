# NFP Hole Collision Tasks

> **Skills required:** Read `.agents/skills/nw_nfp_algorithm/SKILL.md` and `.agents/skills/nw_gpu_taichi/SKILL.md` before starting any task here.

---

## Architecture: One Cache, One Source of Truth

`Shape.nfp_cache[(A, B, angle)]` is the **only** persistent NFP cache. It stores the
geometric relationship between two part shapes at a given relative angle.

`get_global_nfp_for` is **not** a cache — it is a pure function that builds placement
collision data fresh on each call by iterating `sheet.parts`, looking up pairwise NFPs
from `Shape.nfp_cache`, translating each to the placed part's position, and returning
a local result dict.

**There is no sheet-level NFP cache.** `sheet.nfp_cache` is a design error and must
be removed (see NFP-006).

---

## Root Cause: Mixed Shell/Hole Test

The GPU No-Union scoring path currently passes flat accumulated `shells` and `holes`
lists to `compute_batch_pip_with_holes`. The collision test is:

```
collision = (inside ANY shell from ALL parts) AND NOT (inside ANY hole from ALL parts)
```

This is **semantically wrong** when multiple placed parts are on the sheet. A hole
belonging to placed part A should only cancel a collision with A's shells — it must
never cancel a collision with part B's shells.

**Failure scenario** (causes overlaps):

```
Placed: A (donut with hole), C (solid, placed inside A's hole)
Placing: D

shells = [A_shells, C_shells]
holes  = [A_hole_IFP]

Candidate P (inside A's hole AND inside C's shells):
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

## NFP-006: Remove `sheet.nfp_cache`; Rewrite `get_global_nfp_for` as Pure Function

| Field | Value |
|-------|-------|
| Complexity | Medium |
| Files | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py`, `nestingworkbench/datatypes/sheet.py`, `nestingworkbench/Tools/Nesting/algorithms/nesting_strategy.py` |
| Depends on | — |
| Priority | HIGH — required before NFP-007 and NFP-012 |

**Context**

`sheet.nfp_cache` and `sheet.nfp_cache_lock` exist on every `Sheet` instance. They store
an incrementally accumulated union of translated pairwise NFPs keyed by `(part_label, angle)`.
This is wrong — the sheet object should not own NFP state. The only NFP cache is
`Shape.nfp_cache[(A, B, angle)]` (pairwise, session-lifetime).

`get_global_nfp_for` must become a pure function that computes the result fresh on each
call with no persistent side effects.

**What to do**

**Step 1 — Remove sheet-level cache from `sheet.py`**

In `Sheet.__init__` (lines ~40–41), delete:
```python
self.nfp_cache = {}
self.nfp_cache_lock = threading.Lock()
```

**Step 2 — Rewrite `get_global_nfp_for` in `minkowski_engine.py`**

Replace the entire `get_global_nfp_for` method with:

```python
def get_global_nfp_for(self, part_to_place, angle, sheet):
    """
    Build placement collision data for part_to_place at angle on sheet.

    Pure function — result is NOT cached. Shape.nfp_cache[(A, B, angle)]
    is the only persistent cache (pairwise geometric relationships).

    Returns dict:
      'polygon'      — Polygon: CPU path incremental union (visualization + PIP)
      'points'       — list[Point]: candidate positions (discretized NFP edges)
      'per_part_nfps'— list[{'shells': [...], 'holes': [...]}]: one entry per
                       placed part; used for per-part GPU collision scoring
    Returns None if any pairwise NFP has an error flag.
    """
    part_label = part_to_place.source_freecad_object.Label
    polygon = Polygon()
    points = []
    per_part_nfps = []

    for p in sheet.parts:
        placed_label = p.shape.source_freecad_object.Label
        placed_angle = p.angle

        relative_angle = (angle - placed_angle) % 360.0
        if abs(relative_angle - 360.0) < 1e-5:
            relative_angle = 0.0
        relative_angle = round(relative_angle, 4)

        nfp_cache_key = (
            placed_label, part_label, relative_angle,
            part_to_place.spacing, part_to_place.deflection, part_to_place.simplification
        )

        with Shape.nfp_cache_lock:
            nfp_data = Shape.nfp_cache.get(nfp_cache_key)

        # If batch-cached entry has empty holes for a placed part that has interior rings,
        # force recompute via _calculate_and_cache_nfp_gpu to get correct IFP hole data.
        if (nfp_data is not None
                and self.use_gpu
                and not nfp_data.get('holes')
                and p.shape.original_polygon
                and list(p.shape.original_polygon.interiors)):
            nfp_data = None

        if not nfp_data:
            if self.use_gpu:
                nfp_data = self._calculate_and_cache_nfp_gpu(
                    p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                )
            else:
                nfp_data = self._calculate_and_cache_nfp(
                    p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                )

        if not nfp_data:
            continue
        if nfp_data.get('error'):
            self.log(f"Skipping rotation due to NFP error: {nfp_data['error']}")
            return None

        cent = p.shape.centroid

        if self.use_gpu:
            part_shells = []
            for piece in nfp_data.get('shells', []):
                rotated = rotate(piece, placed_angle, origin=(0, 0))
                part_shells.append(translate(rotated, xoff=cent.x, yoff=cent.y))

            part_holes = []
            for piece in nfp_data.get('holes', []):
                rotated = rotate(piece, placed_angle, origin=(0, 0))
                part_holes.append(translate(rotated, xoff=cent.x, yoff=cent.y))

            per_part_nfps.append({'shells': part_shells, 'holes': part_holes})

            # Candidate points: discretize the NFP boundary edges
            master = nfp_data.get('polygon')
            if master and not master.is_empty:
                rotated_m = rotate(master, placed_angle, origin=(0, 0))
                translated_m = translate(rotated_m, xoff=cent.x, yoff=cent.y)
                points.extend(self._discretize_edge(translated_m.exterior))
                for interior in translated_m.interiors:
                    points.extend(self._discretize_edge(interior))
            else:
                for piece in part_shells:
                    points.extend(self._discretize_edge(piece.exterior))
        else:
            # CPU path
            master = nfp_data.get('polygon')
            if not master:
                continue
            rotated = rotate(master, placed_angle, origin=(0, 0))
            translated = translate(rotated, xoff=cent.x, yoff=cent.y)
            if polygon.is_empty:
                polygon = translated
            else:
                polygon = polygon.union(translated)
            points.extend(self._discretize_edge(translated.exterior))
            for interior in translated.interiors:
                points.extend(self._discretize_edge(interior))

    return {'polygon': polygon, 'points': points, 'per_part_nfps': per_part_nfps}
```

**Step 3 — Fix `_evaluate_rotation` in `nesting_strategy.py`**

`_evaluate_rotation` currently reads `nfp_entry.get('prepared')` and writes it back to
the entry. Since the entry is no longer cached, build `prepared_nfp` locally:

Replace lines ~124–133:
```python
# OLD
union_poly = nfp_entry['polygon']
prepared_nfp = nfp_entry.get('prepared')
if not prepared_nfp and not union_poly.is_empty:
    prepared_nfp = prep(union_poly)
    with sheet.nfp_cache_lock:
        if not nfp_entry.get('prepared'):
            nfp_entry['prepared'] = prepared_nfp
        else:
            prepared_nfp = nfp_entry['prepared']
```
with:
```python
# NEW
union_poly = nfp_entry['polygon']
prepared_nfp = prep(union_poly) if not union_poly.is_empty else None
```

**Acceptance criteria**

1. `Sheet.__init__` no longer creates `nfp_cache` or `nfp_cache_lock`.
2. `get_global_nfp_for` has no references to `sheet.nfp_cache`.
3. Return value has keys `polygon`, `points`, `per_part_nfps`.
4. CPU-path nesting still places parts correctly (no regression).
5. GPU-path nesting still places parts correctly (no regression).

---

## NFP-007: Per-Part Collision Evaluation in `score_candidates_gpu`

| Field | Value |
|-------|-------|
| Complexity | Medium |
| Files | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |
| Depends on | NFP-006 |

**Context**

After NFP-006, `get_global_nfp_for` returns `per_part_nfps` — one `{shells, holes}` dict
per placed part. `score_candidates_gpu` must use this for collision testing instead of
the flat combined lists it currently passes to `compute_batch_pip_with_holes`.

The correct rule: a candidate is **rejected** if it collides with ANY placed part.
Collision with part i = (inside part_i.shells) AND NOT (inside part_i.holes).

**What to do**

Replace lines ~311–320 in `score_candidates_gpu`:

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
    results = np.zeros(len(points), dtype=np.int32)
elif not any(p['holes'] for p in per_part):
    # Fast path: no placed part has holes — single combined PIP call
    all_shells = [s for p in per_part for s in p['shells']]
    results = (nfp_gpu_taichi.compute_batch_pip(pts_np, all_shells)
               if all_shells else np.zeros(len(points), dtype=np.int32))
else:
    # Slow path: at least one placed part has holes — must test per-part
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

This also subsumes NFP-012: the fast-path (single combined call when no part has holes)
is included here directly.

**Acceptance criteria**

1. A part placed inside donut A's hole cannot overlap another part C also inside A's hole.
2. A part can still be validly placed inside an empty donut hole (IFP works).
3. With no holed placed parts on the sheet, exactly 1 GPU PIP kernel call per angle.
4. With 1 donut and N solid parts, exactly 2 kernel calls (1 for solids, 1 for donut).
5. Screenshot shows no overlapping parts when filling holes.

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
