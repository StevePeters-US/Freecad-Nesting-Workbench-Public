# Skill: NFP / Minkowski Algorithm

> Read this before modifying NFP, IFP, or Minkowski computation.

## Files to Read First

- `nestingworkbench/Tools/Nesting/algorithms/minkowski_utils.py` — core NFP/IFP math
- `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` — caching + GPU dispatch
- `nestingworkbench/Tools/Nesting/algorithms/nfp_gpu_taichi.py` — Taichi GPU kernel

## Concepts

### No-Fit Polygon (NFP)
The NFP of parts A and B is the locus of all positions where B's reference point would cause B to overlap A. Computed via **Minkowski sum** of A with the reflection of B (−B).

### Inner-Fit Polygon (IFP)
The IFP is the valid region where a part's reference point can be placed inside a container (sheet). Computed via **Minkowski difference** (now named `calculate_inner_fit_polygon()`).

### Convex Decomposition
Non-convex parts are decomposed into convex sub-polygons. The NFP of two non-convex parts is the union of pairwise NFPs of their convex decompositions.

## Key APIs

| Symbol | Location | Purpose |
|--------|----------|---------|
| `MinkowskiEngine.compute_nfp()` | `minkowski_engine.py` | NFP with caching |
| `MinkowskiEngine._calculate_and_cache_nfp_cpu()` | `minkowski_engine.py` | CPU path |
| `MinkowskiEngine._calculate_and_cache_nfp_gpu()` | `minkowski_engine.py` | GPU path (Taichi) |
| `calculate_inner_fit_polygon()` | `minkowski_utils.py` | IFP for sheet containment |
| `minkowski_sum_convex()` | `minkowski_utils.py` | Convex Minkowski sum |
| `convex_decomposition()` | `minkowski_utils.py` | Part → convex sub-polygons |
| `Shape.nfp_cache` | `datatypes/shape.py` | Class-level dict, thread-safe |

## NFP Cache

- Key: `(label_A, label_B, angle_B)` tuple
- Value: Shapely Polygon (the NFP)
- Guarded by `Shape.nfp_cache_lock` (threading.Lock)
- Lost on FreeCAD restart — see TASK-009 for persistence proposal

## GPU Path

The Taichi kernel in `nfp_gpu_taichi.py` supports batched rotation angles but the engine currently sends one angle at a time (see TASK-011). The CPU fallback must always work when Taichi is unavailable.

## Gotchas

- NFP computation is ~80% of total nesting time for complex parts
- The GPU path dispatches one kernel per `(A, B, angle)` — batching is TODO
- Convex decomposition can produce many sub-polygons for complex parts
- Thread safety: `nfp_cache_lock` must be held for all cache reads/writes
