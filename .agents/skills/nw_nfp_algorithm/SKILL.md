---
name: nw_nfp_algorithm
description: NFP/IFP algorithm, two-level cache architecture, GPU/CPU path differences, and hole-scoring correctness. Read before modifying NFP, IFP, or Minkowski computation.
---

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

### Level 2: `get_global_nfp_for` — Pure Placement Function (NOT a cache)

`get_global_nfp_for(part, angle, sheet)` is a **pure function** — it computes the
placement collision data fresh on each call with no persistent side effects. There is
no sheet-level NFP cache.

On each call it:
1. Iterates `sheet.parts`
2. Looks up each pairwise NFP from `Shape.nfp_cache[(placed, part, angle)]`
3. Translates shells/holes to the placed part's actual sheet position
4. Returns a local result dict

**Return value:**
```python
{
    'polygon': Polygon,         # CPU path: incremental union of translated NFPs
                                # GPU path: visualization only
    'points': [Point, ...],     # candidate positions (discretized NFP boundary edges)
    'per_part_nfps': [          # GPU: one entry per placed part for correct scoring
        {'shells': [...], 'holes': [...]},  # placed part 0
        {'shells': [...], 'holes': [...]},  # placed part 1
    ],
}
```

> **CRITICAL — hole scoring:** Use `per_part_nfps` for GPU collision scoring, NOT a flat
> combined shells/holes list. Mixing all holes into one list causes A's hole IFP to cancel
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
  get_global_nfp_for(B, angle, sheet)   ← pure function, no persistent state
    → iterates sheet.parts
    → reads Shape.nfp_cache[(placed_A, B, angle)] for each placed A
    → translates pairwise NFP shells/holes to A's position on sheet
    → returns {polygon, points, per_part_nfps} as a local dict
                                              ↓
  score_candidates_gpu() / _evaluate_rotation()
    → receives the local dict from get_global_nfp_for
    → GPU: per-part loop over per_part_nfps, OR results
    → CPU: prep(polygon).contains(pt)
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
- **`Shape.nfp_cache` is the only persistent NFP cache.** There is no sheet-level cache.
  `get_global_nfp_for` is a pure function — its return value is a local dict, not stored.
- Thread safety: `Shape.nfp_cache_lock` must be held for all `Shape.nfp_cache` reads/writes.
- GPU `shells` pieces are in **centered space** (polygon translated to origin before NFP computation).
  They are translated to the placed part's actual sheet position in `get_global_nfp_for`.
- `precompute_nfp_batch` and `_calculate_and_cache_nfp_gpu` must produce the **same cache
  format** or consumers that check `nfp_data.get('shells')` will silently get empty lists.
