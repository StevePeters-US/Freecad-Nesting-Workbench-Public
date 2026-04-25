
import math
import time
import numpy as np
import FreeCAD
from threading import Lock
from shapely.geometry import Polygon, Point
from shapely.affinity import translate, rotate
from . import minkowski_utils
try:
    from . import nfp_gpu_taichi
except ImportError as e:
    import traceback
    traceback.print_exc()
    import FreeCAD
    FreeCAD.Console.PrintError(f"nfp_gpu_taichi Import Error: {e}\n")
    nfp_gpu_taichi = None
from ....datatypes.shape import Shape

class MinkowskiEngine:
    """
    Handles geometric operations for Minkowski nesting, such as NFP generation,
    candidate point finding, and placement validation.
    """
    def __init__(self, bin_width, bin_height, step_size, discretize_edges=True, log_callback=None, use_gpu=False, verbose=False, search_direction=(0, -1)):
        self.bin_width = bin_width
        self.bin_height = bin_height
        self.step_size = step_size
        self.discretize_edges = discretize_edges
        self.log_callback = log_callback
        self.verbose = verbose
        
        self.use_gpu = use_gpu and nfp_gpu_taichi and nfp_gpu_taichi.is_available() # Check availability
        self.search_direction = search_direction
        self._log_lock = Lock()
        
        if use_gpu:
            if self.use_gpu:
                backend = nfp_gpu_taichi.get_backend() if nfp_gpu_taichi else "unknown"
                self.log(f"GPU acceleration enabled (Taichi backend: {backend}).")
            else:
                self.log("GPU acceleration requested but Taichi is not available or only has a CPU backend. Falling back to CPU.")

        self.bin_polygon = Polygon([(0, 0), (self.bin_width, 0), (self.bin_width, self.bin_height), (0, self.bin_height)])
        self._perf_stats = {'cache_hits': 0, 'cache_misses': 0, 'nfp_compute_ms': 0.0}
        self._perf_lock = Lock()

    def log(self, message):
        if self.log_callback:
            with self._log_lock:
                self.log_callback("MINKOWSKI_ENGINE: " + message)
        else:
             FreeCAD.Console.PrintMessage(f"MINKOWSKI_ENGINE: {message}\n")

    def get_global_nfp_for(self, part_to_place, angle, sheet):
        """
        Build placement collision data for part_to_place at angle on sheet.

        Both CPU and GPU paths use exact Minkowski sum NFPs. GPU additionally
        accumulates per_part_nfps (convex shells from the exact NFP polygon)
        for batch PIP scoring on the GPU.

        Returns dict:
          'polygon'      — Polygon: incremental union (CPU PIP + visualization)
          'points'       — (N,2) float32: candidate positions
          'per_part_nfps'— list[{'shells': [...], 'holes': [...]}]: GPU PIP data
        Returns None if any pairwise NFP has an error flag.
        """
        part_label = part_to_place.source_freecad_object.Label
        polygon = Polygon()
        _pt_arrays = []
        per_part_nfps = []
        t0_total = time.perf_counter()
        n_hits = 0
        n_misses = 0

        for p in sheet.parts:
            placed_label = p.shape.source_freecad_object.Label
            placed_angle = p.angle

            relative_angle = (angle - placed_angle) % 360.0
            if abs(relative_angle - 360.0) < 1e-5:
                relative_angle = 0.0
            relative_angle = round(relative_angle, 4)

            nfp_cache_key = (
                placed_label, part_label, relative_angle,
                part_to_place.spacing, part_to_place.deflection, part_to_place.simplification,
            )

            nfp_data = Shape.nfp_cache.get(nfp_cache_key)

            if not nfp_data:
                n_misses += 1
                t_miss = time.perf_counter()
                nfp_data = self._calculate_and_cache_nfp(
                    p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                )
                dt_miss = (time.perf_counter() - t_miss) * 1000
                if self.verbose:
                    self.log(f"[PERF] NFP cache MISS key={nfp_cache_key[:3]} angle={relative_angle:.1f} -> {dt_miss:.1f}ms")
                with self._perf_lock:
                    self._perf_stats['nfp_compute_ms'] += dt_miss
            else:
                n_hits += 1

            if not nfp_data:
                continue
            if nfp_data.get('error'):
                self.log(f"Skipping rotation due to NFP error: {nfp_data['error']}")
                return None

            cent = p.shape.centroid
            master = nfp_data.get('polygon')
            if not master:
                continue

            rotated = rotate(master, placed_angle, origin=(0, 0))
            translated = translate(rotated, xoff=cent.x, yoff=cent.y)
            polygon = translated if polygon.is_empty else polygon.union(translated)

            # Candidate points — use pre-discretized local_points when available
            local_pts = nfp_data.get('local_points')
            if local_pts is not None and len(local_pts):
                pts = local_pts.copy()
                if abs(placed_angle) > 1e-9:
                    a = math.radians(placed_angle)
                    ca, sa = math.cos(a), math.sin(a)
                    pts = pts @ np.array([[ca, -sa], [sa, ca]], dtype=np.float64).T
                pts[:, 0] += cent.x
                pts[:, 1] += cent.y
                _pt_arrays.append(pts.astype(np.float32))
            else:
                ring_pts = self._discretize_ring_np(translated.exterior, self.step_size)
                if len(ring_pts):
                    _pt_arrays.append(ring_pts.astype(np.float32))
                for interior in translated.interiors:
                    int_pts = self._discretize_ring_np(interior, self.step_size)
                    if len(int_pts):
                        _pt_arrays.append(int_pts.astype(np.float32))

            # GPU PIP shells — convex decomposition of the translated exact NFP polygon
            if self.use_gpu:
                raw_shells = nfp_data.get('shells', [])
                raw_holes = nfp_data.get('holes', [])
                part_shells = []
                for shell in raw_shells:
                    r = rotate(shell, placed_angle, origin=(0, 0)) if abs(placed_angle) > 1e-9 else shell
                    part_shells.append(translate(r, xoff=cent.x, yoff=cent.y))
                part_holes = []
                for hole in raw_holes:
                    r = rotate(hole, placed_angle, origin=(0, 0)) if abs(placed_angle) > 1e-9 else hole
                    part_holes.append(translate(r, xoff=cent.x, yoff=cent.y))
                per_part_nfps.append({'shells': part_shells, 'holes': part_holes})

        dt_total = (time.perf_counter() - t0_total) * 1000
        with self._perf_lock:
            self._perf_stats['cache_hits'] += n_hits
            self._perf_stats['cache_misses'] += n_misses
        if _pt_arrays:
            all_pts = np.concatenate(_pt_arrays, axis=0)
            grid = max(1.0, self.step_size)
            rounded = np.round(all_pts / grid).astype(np.int32)
            _, unique_idx = np.unique(rounded, axis=0, return_index=True)
            points = all_pts[unique_idx]
        else:
            points = np.empty((0, 2), dtype=np.float32)
        if self.verbose and (n_misses > 0 or dt_total > 10.0):
            self.log(f"[PERF] get_global_nfp_for angle={angle:.1f} "
                     f"hits={n_hits} misses={n_misses} "
                     f"total={dt_total:.1f}ms candidates={len(points)}")
        return {'polygon': polygon, 'points': points, 'per_part_nfps': per_part_nfps}

    def precompute_nfp_batch(self, part_to_place, angles, sheet):
        """No-op: NFP computation is now always done via exact CPU Minkowski sum.
        Background precomputation is handled by _submit_precomputation in the nester."""
        pass

    @staticmethod
    def score_gravity(pts_np, valid, direction):
        """Score candidates by gravity direction. Lower metric = better (furthest along direction).

        pts_np: (N, 2) float array of candidate positions
        valid:  (N,) bool mask — invalid positions get metric=inf
        direction: (gx, gy) unit vector pointing toward preferred side
        Returns: (best_idx, metric) or (None, inf) when no valid candidates exist.
        """
        gx, gy = direction
        scores = np.where(valid, -(pts_np[:, 0] * gx + pts_np[:, 1] * gy), np.inf)
        best_idx = int(np.argmin(scores))
        metric = float(scores[best_idx])
        if not np.isfinite(metric):
            return None, float('inf')
        return best_idx, metric

    def score_candidates_gpu(self, part_to_place, rotation_candidates):
        """Calculates scores for multiple candidates using GPU PIP scoring.

        rotation_candidates: list of (angle, points, nfp_entry) tuples.
        nfp_entry is the dict already returned by get_global_nfp_for — do NOT
        call get_global_nfp_for again here.
        """
        if not self.use_gpu or not nfp_gpu_taichi:
             return None

        best_overall = {'metric': float('inf')}
        t0_score = time.perf_counter()
        total_candidates = sum(len(pts) for _, pts, _ in rotation_candidates)
        if self.verbose:
            self.log(f"[PERF] score_candidates_gpu: {len(rotation_candidates)} angles, "
                     f"{total_candidates} total candidates")

        for angle, points, nfp_entry in rotation_candidates:
            pts_np = points if points.dtype == np.float32 else points.astype(np.float32)
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
            
            # GPU-005: Batch container bounds check
            rotated_poly = rotate(part_to_place.original_polygon, angle, origin='centroid')
            centroid = rotated_poly.centroid
            min_x, min_y, max_x, max_y = rotated_poly.bounds
            rel_extents = np.array([
                min_x - centroid.x, 
                min_y - centroid.y, 
                max_x - centroid.x, 
                max_y - centroid.y
            ], dtype=np.float32)
            
            extents_np = np.tile(rel_extents, (len(points), 1))
            bounds_results = np.zeros(len(points), dtype=np.int32)
            
            with nfp_gpu_taichi._kernel_lock:
                nfp_gpu_taichi.bounds_check_kernel(
                    len(points), pts_np, extents_np, 
                    float(self.bin_width), float(self.bin_height), 
                    bounds_results
                )
            
            valid = (results == 0) & (bounds_results == 1)
            n_scored = int(valid.sum())
            if n_scored > 0:
                best_idx, metric = MinkowskiEngine.score_gravity(pts_np, valid, self.search_direction)
                if best_idx is not None and metric < best_overall['metric']:
                    best_overall = {
                        'x': float(pts_np[best_idx, 0]),
                        'y': float(pts_np[best_idx, 1]),
                        'angle': angle,
                        'metric': metric,
                    }
            
            if self.verbose and n_scored > 0:
                self.log(f"GPU scored {n_scored} candidates in batch at angle {angle}")
        dt_score = (time.perf_counter() - t0_score) * 1000
        if self.verbose:
            self.log(f"[PERF] score_candidates_gpu total: {dt_score:.1f}ms best={best_overall.get('metric', 'inf'):.2f}")
        return best_overall

    def _calculate_and_cache_nfp(self, shape_A, angle_A, part_to_place, angle_B, cache_key):
        with Shape.nfp_cache_lock:
            cached_nfp_data = Shape.nfp_cache.get(cache_key)
            if cached_nfp_data: return cached_nfp_data
        try:
            mA, mB = shape_A.original_polygon, part_to_place.original_polygon
            cA, cB = mA.centroid, mB.centroid
            poly_A_centered = translate(mA, -cA.x, -cA.y)
            poly_B_centered = translate(mB, -cB.x, -cB.y)
            nfp_exterior = minkowski_utils.minkowski_sum(poly_A_centered, angle_A, False, poly_B_centered, angle_B, True, self.log)
            nfp_interiors = []
            if poly_A_centered.interiors:
                B_rot = rotate(poly_B_centered, angle_B, origin=(0,0))
                for hole in poly_A_centered.interiors:
                    hole_poly = Polygon(hole.coords)
                    if (B_rot.bounds[2] - B_rot.bounds[0] < hole_poly.bounds[2] - hole_poly.bounds[0] and
                        B_rot.bounds[3] - B_rot.bounds[1] < hole_poly.bounds[3] - hole_poly.bounds[1] and
                        B_rot.area < hole_poly.area):
                        ifp = minkowski_utils.calculate_inner_fit_polygon(hole_poly, 0, poly_B_centered, angle_B, self.log)
                        if ifp and not ifp.is_empty:
                            if ifp.geom_type == 'Polygon': nfp_interiors.append(ifp.exterior)
                            elif ifp.geom_type == 'MultiPolygon':
                                for p in ifp.geoms: nfp_interiors.append(p.exterior)
            master_nfp = Polygon(nfp_exterior.exterior, nfp_interiors) if nfp_exterior and nfp_exterior.area > 0 else None
            if master_nfp:
                rings = [master_nfp.exterior] + list(master_nfp.interiors)
                pts_parts = [self._discretize_ring_np(r, self.step_size) for r in rings]
                local_pts = np.concatenate(pts_parts, axis=0) if pts_parts else np.empty((0, 2), dtype=np.float64)
                # Convex shells for GPU PIP — decomposed from the exact NFP result polygon
                shells = minkowski_utils.decompose_if_needed(Polygon(master_nfp.exterior), self.log)
                holes = []
                for interior in master_nfp.interiors:
                    holes.extend(minkowski_utils.decompose_if_needed(Polygon(interior.coords), self.log))
                nfp_data = {"polygon": master_nfp, "local_points": local_pts, "shells": shells, "holes": holes}
            else:
                nfp_data = {}
        except Exception as e:
            self.log(f"Error calculating NFP for {cache_key}: {e}")
            nfp_data = {'error': str(e)}
        with Shape.nfp_cache_lock: Shape.nfp_cache[cache_key] = nfp_data
        return nfp_data

    def get_perf_stats(self):
        with self._perf_lock:
            return dict(self._perf_stats)

    def reset_perf_stats(self):
        with self._perf_lock:
            self._perf_stats = {'cache_hits': 0, 'cache_misses': 0, 'nfp_compute_ms': 0.0}

    @staticmethod
    def _discretize_ring_np(ring, step_size):
        """Vectorized ring discretisation. Returns (N, 2) float64 array.

        Replaces the Shapely interpolate() loop — samples at equal arc-length
        intervals using numpy cumulative distance + np.interp.
        """
        coords = np.array(ring.coords, dtype=np.float64)
        diffs = np.diff(coords, axis=0)
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_dist = np.empty(len(seg_lens) + 1, dtype=np.float64)
        cum_dist[0] = 0.0
        np.cumsum(seg_lens, out=cum_dist[1:])
        total = cum_dist[-1]
        if total < step_size:
            return coords[:1]
        n = max(2, int(total / step_size))
        sample_dists = np.linspace(0.0, total, n, endpoint=False)
        xs = np.interp(sample_dists, cum_dist, coords[:, 0])
        ys = np.interp(sample_dists, cum_dist, coords[:, 1])
        return np.column_stack([xs, ys])

    def _discretize_edge(self, line):
        pts = self._discretize_ring_np(line, self.step_size)
        return [Point(float(r[0]), float(r[1])) for r in pts]
