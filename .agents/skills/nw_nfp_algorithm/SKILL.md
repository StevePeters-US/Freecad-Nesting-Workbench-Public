# Skill: NFP / Minkowski Algorithm

> Read this before modifying NFP, IFP, or Minkowski computation.

## Files to Read First

- `nestingworkbench/Tools/Nesting/algorithms/minkowski_utils.py` — core NFP/IFP math
- `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` — caching + GPU dispatch
- `nestingworkbench/Tools/Nesting/algorithms/nfp_gpu_taichi.py` — Taichi GPU kernels

## Concepts

### No-Fit Polygon (NFP)
The NFP of parts A and B is the locus of all positions where B's reference point would cause
B to overlap A. Computed via **Minkowski sum** of A with the reflection of B (−B).

### Inner-Fit Polygon (IFP)
The IFP is the valid region where a part's reference point can be placed inside a container
(sheet or hole). Computed via **Minkowski difference** (`calculate_inner_fit_polygon()`).

### Convex Decomposition
Non-convex parts are decomposed into convex sub-polygons via triangulation
(`decompose_if_needed()`). The NFP of two non-convex parts is the union of pairwise NFPs
of their convex decompositions.

---

## Two-Level NFP Cache Architecture

**This is the core design. Do not collapse these two levels into one.**

### Level 1: Pairwise NFP Cache (`Shape.nfp_cache`)

Stores the **geometric relationship between two part shapes** at a given relative angle.
This is the expensive computation (~80% of total nesting time). Pre-computing these is the
primary performance strategy.

| Attribute | Value |
|-----------|-------|
| Location | `Shape.nfp_cache` (class-level dict) |
| Key | `(label_A, label_B, angle, spacing, deflection, simplification)` |
| Thread safety | `Shape.nfp_cache_lock` |
| Lifetime | Session — survives across multiple nesting runs |

**GPU path format** (produced by `_calculate_and_cache_nfp_gpu` and `precompute_nfp_batch`):
```python
{
    'shells': [Polygon, ...],  # convex hull pieces of the solid forbidden area
    'holes': [Polygon, ...],   # IFP pieces for holes in part A (allowed sub-regions)
    'polygon': Polygon | None  # best-effort union — VISUALIZATION ONLY, not for scoring
}
```

**CPU path format** (produced by `_calculate_and_cache_nfp`):
```python
{
    'polygon': Polygon  # full NFP polygon with hole interiors
}
```

### Level 2: Sheet Accumulation Cache (`sheet.nfp_cache`)

Stores the **accumulated forbidden region** for a specific part+angle on a specific sheet.
Built incrementally: each time a new part is placed on the sheet, only the new pairwise
NFP is translated and added (tracked by `last_part_idx`).

| Attribute | Value |
|-----------|-------|
| Location | `sheet.nfp_cache` (per-Sheet instance dict) |
| Key | `(label_part_to_place, angle)` |
| Thread safety | `sheet.nfp_cache_lock` |
| Lifetime | Per-sheet — reset when the sheet is reset |

**Sheet accumulation entry format:**
```python
{
    'polygon': Polygon,        # incremental union of all translated pairwise NFPs
                               # CPU path: used for PIP test (via `prepared`)
                               # GPU path: candidate discretization + visualization only
    'last_part_idx': int,      # number of placed parts already processed
    'points': [Point, ...],    # candidate positions (discretized NFP boundary edges)
    'prepared': PreparedGeometry | None,  # shapely.prepared.prep(polygon) — lazy
    'shells': [Polygon, ...],  # GPU: flat list of ALL placed parts' shell pieces
    'holes': [Polygon, ...],   # GPU: flat list of ALL placed parts' hole pieces
    'per_part_nfps': [         # GPU path: per-placed-part shell/hole pairs for correct scoring
        {'shells': [...], 'holes': [...]},  # placed part 0
        {'shells': [...], 'holes': [...]},  # placed part 1
    ],
}
```

> **CRITICAL — hole scoring:** Use `per_part_nfps` for GPU collision scoring, NOT the flat
> `shells`/`holes` lists. Mixing all holes into one list causes A's hole IFP to cancel
> collisions with unrelated part B's shells, allowing overlapping placements inside A's hole.
> Each hole must only cancel its own part's shells. See `todo_nfp.md` NFP-006/007.

### Pre-Caching Flow

```
Before placement begins:
  precompute_nfp_batch()
    → compute_nfp_batch() [GPU] or _calculate_and_cache_nfp() [CPU]
    → writes to Shape.nfp_cache[(A, B, angle)]
                                              ↓
During placement of part B:
  get_global_nfp_for(B, angle, sheet)
    → reads Shape.nfp_cache[(placed_A, B, angle)] for each placed A
    → translates pairwise NFP to A's position on sheet
    → accumulates into sheet.nfp_cache[(B, angle)]['shells']/'polygon'/'points'
                                              ↓
  score_candidates_gpu() / _evaluate_rotation()
    → reads sheet.nfp_cache[(B, angle)]
    → GPU: compute_batch_pip_with_holes(pts, shells, holes)
    → CPU: prepared_nfp.contains(pt)
```

---

## Key APIs

| Symbol | Location | Purpose |
|--------|----------|---------|
| `MinkowskiEngine.get_global_nfp_for(part, angle, sheet)` | `minkowski_engine.py` | Build/return sheet accumulation entry |
| `MinkowskiEngine._calculate_and_cache_nfp(A, aA, B, aB, key)` | `minkowski_engine.py` | CPU pairwise NFP |
| `MinkowskiEngine._calculate_and_cache_nfp_gpu(A, aA, B, aB, key)` | `minkowski_engine.py` | GPU pairwise NFP |
| `MinkowskiEngine.precompute_nfp_batch(part, angles, sheet)` | `minkowski_engine.py` | Background pre-caching |
| `MinkowskiEngine.score_candidates_gpu(part, candidates, sheet)` | `minkowski_engine.py` | GPU candidate scoring |
| `calculate_inner_fit_polygon(poly1, a1, poly2, a2, log)` | `minkowski_utils.py` | IFP for holes |
| `minkowski_sum_convex(p1, p2)` | `minkowski_utils.py` | Convex Minkowski sum |
| `decompose_if_needed(polygon, log)` | `minkowski_utils.py` | Non-convex → convex triangles |
| `Shape.nfp_cache` | `datatypes/shape.py` | Class-level pairwise cache dict |

---

## GPU Path: No-Union Scoring

The GPU scoring path avoids `unary_union` entirely for collision testing:

1. `_calculate_and_cache_nfp_gpu` stores individual convex hull pieces (`shells`) rather than
   their union. The union (`polygon`) is computed separately for visualization only.
2. `get_global_nfp_for` (GPU branch) translates and accumulates `shells`/`holes` per placed part
   into `sheet.nfp_cache[...]['shells']`/`['holes']`.
3. `score_candidates_gpu` calls `compute_batch_pip_with_holes(pts, shells, holes)`:
   - A candidate is **colliding** if it is inside any shell AND NOT inside any hole.
   - This correctly handles holes in placed parts (parts that fit inside holes are not blocked).

**Critical:** `precompute_nfp_batch` must also write `shells`/`holes` format (not just `polygon`)
or the pre-cached entries will produce empty `shells` and defeat pre-caching entirely.
See `todo_nfp.md` NFP-001 for the fix.

---

## Gotchas

- NFP computation is ~80% of total nesting time for complex parts
- **Never build the sheet-level union inside a pairwise NFP cache entry.** The pairwise cache
  must only store the A+B relationship; position on the sheet is added in `get_global_nfp_for`.
- Thread safety: `nfp_cache_lock` must be held for all `Shape.nfp_cache` reads/writes
- The `sheet.nfp_cache` `polygon` field builds incrementally — do NOT replace it on each call;
  use `entry['polygon'].union(new_translated)` and extend `entry['points']` (do not replace).
- GPU `shells` pieces are in **centered space** (polygon translated to origin before NFP computation).
  They are translated to the placed part's actual sheet position in `get_global_nfp_for`.
- `precompute_nfp_batch` and `_calculate_and_cache_nfp_gpu` must produce the **same cache
  format** or consumers that check `nfp_data.get('shells')` will silently get empty lists.
