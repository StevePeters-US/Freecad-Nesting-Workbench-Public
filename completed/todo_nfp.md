# Completed — NFP Caching Tasks (from todo_nfp.md)

Archive of completed tasks related to NFP caching and GPU optimization.

---

- [x] **NFP-001**: Fix `precompute_nfp_batch` cache format in `minkowski_engine.py` (**2026-03-27**)

<details>
<summary>Details</summary>

| Field       | Value |
|-------------|-------|
| Complexity  | Low |
| Component   | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |

**Context** — Fixed a regression where background pre-computation only stored the unioned polygon, breaking the GPU's No-Union scoring path which requires individual `shells`.

**What was done**
1. Updated `precompute_nfp_batch` to include `shells` and `holes` in the pairwise NFP cache.
2. Verified that `shells` is populated with the individual convex hull pieces computed on the GPU.
</details>

- [x] **NFP-002**: Fix `score_candidates_gpu` to use `shells`/`holes` not `convex_pieces` (**2026-03-27**)

<details>
<summary>Details</summary>

| Field       | Value |
|-------------|-------|
| Complexity  | Low |
| Component   | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |

**Context** — Updated the GPU scoring path to use the new standardized data structure and hole-aware collision kernel.

**What was done**
1. Replaced the stale `convex_pieces` lookup with `shells` and `holes`.
2. Switched from `compute_batch_pip` to `compute_batch_pip_with_holes`.
3. Removed the expensive fallback decomposition of the sheet-level union.
</details>

- [x] **NFP-003**: Remove stale `convex_pieces` fallback compatibility shim (**2026-03-27**)

<details>
<summary>Details</summary>

| Field       | Value |
|-------------|-------|
| Complexity  | Low |
| Component   | `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` |

**Context** — Cleaned up the legacy `convex_pieces` key from the generator path as it's no longer used.

**What was done**
1. Removed the shim from `get_global_nfp_for`.
2. Verified no other references to `convex_pieces` exist in the codebase.
</details>

- [x] **NFP-004**: Add regression test for pre-cache round-trip in `tests/test_nfp_cache.py` (**2026-03-27**)

<details>
<summary>Details</summary>

| Field       | Value |
|-------------|-------|
| Complexity  | Low |
| Component   | `tests/test_nfp_cache.py` |

**Context** — Added a test to prevent the NFP cache format regression from reappearing.

**What was done**
1. Created a new test file that mocks the nesting environment.
2. Verified that pre-computed NFPs are correctly formatted for the GPU path.
3. Successfully ran the test with `pytest`.
</details>

- [x] **NFP-005**: Update `nw_gpu_taichi` skill GPU coverage table (**2026-03-27**)

<details>
<summary>Details</summary>

| Field       | Value |
|-------------|-------|
| Complexity  | Trivial |
| Component   | `.agents/skills/nw_gpu_taichi/SKILL.md` |

**Context** — Updated the project documentation to accurately reflect the implemented state of the GPU pipeline.

**What was done**
1. Marked convex hull and conservative union as GPU-accelerated.
2. Added detailed documentation for the No-Union shells/holes architecture.
</details>
