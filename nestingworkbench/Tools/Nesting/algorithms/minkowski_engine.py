
import math
import time
import numpy as np
import FreeCAD
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from shapely.geometry import Polygon, Point, MultiPoint
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

class _CoordsPolygon:
    """Lightweight shell wrapper for GPU PIP — only provides .exterior.coords.
    Avoids creating full Shapely Polygon objects during per-shell transforms."""
    class _Ext:
        __slots__ = ('coords',)
        def __init__(self, coords): self.coords = coords
    __slots__ = ('exterior',)
    def __init__(self, coords): self.exterior = self._Ext(coords)


def _make_shells_batch(hulls):
    """Pre-convert shell polygons to a single batched numpy array for fast transforms.

    Called once at cache-write time. Result stored as 'shells_batch' in nfp_data.
    Returns dict: {'coords': (N,2) float64, 'split_at': int64 array of split indices}.
    """
    if not hulls:
        return {'coords': np.empty((0, 2), dtype=np.float64), 'split_at': np.empty(0, dtype=np.int64)}
    arrays = [np.array(h.exterior.coords, dtype=np.float64) for h in hulls]
    lengths = [len(a) for a in arrays]
    split_at = np.cumsum(lengths)[:-1]
    return {'coords': np.vstack(arrays), 'split_at': split_at}


def _xform_shells_batched(batch, placed_angle_deg, dx, dy):
    """Transform pre-batched shells. Single numpy op regardless of shell count.

    ~100x faster than _xform_shells_numpy for large shell counts (e.g. 2209 shells)
    because all coordinates are transformed with one matrix multiply instead of N
    individual np.array(shell.exterior.coords) conversions.
    """
    all_coords = batch['coords']
    if len(all_coords) == 0:
        return []
    transformed = all_coords.copy()
    if abs(placed_angle_deg) > 1e-9:
        a = math.radians(placed_angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        rot = np.array([[ca, -sa], [sa, ca]], dtype=np.float64)
        transformed = transformed @ rot.T
    transformed[:, 0] += dx
    transformed[:, 1] += dy
    shell_arrays = np.split(transformed, batch['split_at'])
    return [_CoordsPolygon(arr) for arr in shell_arrays]


def _xform_shells_numpy(shells, placed_angle_deg, dx, dy):
    """Fallback: rotate+translate per-shell when no pre-batch is available."""
    if not shells:
        return []
    result = []
    if abs(placed_angle_deg) > 1e-9:
        a = math.radians(placed_angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        rot = np.array([[ca, -sa], [sa, ca]], dtype=np.float64)
        for shell in shells:
            coords = np.array(shell.exterior.coords, dtype=np.float64)
            coords[:, :2] = coords[:, :2] @ rot.T
            coords[:, 0] += dx
            coords[:, 1] += dy
            result.append(_CoordsPolygon(coords))
    else:
        off = np.array([dx, dy], dtype=np.float64)
        for shell in shells:
            coords = np.array(shell.exterior.coords, dtype=np.float64) + off
            result.append(_CoordsPolygon(coords))
    return result


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
        
        # Local cache for centered decompositions to avoid redundant Shapely calls
        self._decomp_cache = {} 
        self._decomp_lock = Lock()
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
                part_to_place.spacing, part_to_place.deflection, part_to_place.simplification
            )

            nfp_data = Shape.nfp_cache.get(nfp_cache_key)

            # Safety net: Pass 2 IFP fill-in may have failed (e.g. exception in thread).
            # Fill IFP on-demand rather than discarding the valid shells from Pass 1.
            if (nfp_data is not None
                    and self.use_gpu
                    and nfp_data.get('holes') is None
                    and p.shape.original_polygon
                    and list(p.shape.original_polygon.interiors)):
                nfp_holes = self._compute_ifp_for_hole_shape(p.shape, part_to_place, relative_angle)
                with Shape.nfp_cache_lock:
                    entry = Shape.nfp_cache.get(nfp_cache_key)
                    if entry is not None and entry.get('holes') is None:
                        entry['holes'] = nfp_holes
                nfp_data = Shape.nfp_cache.get(nfp_cache_key)

            if not nfp_data:
                n_misses += 1
                t_miss = time.perf_counter()
                if self.use_gpu:
                    nfp_data = self._calculate_and_cache_nfp_gpu(
                        p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                    )
                else:
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

            if self.use_gpu:
                t_xform = time.perf_counter()

                # Always fetch raw_shells (needed for fallback discretize when master is empty).
                raw_shells = nfp_data.get('shells', [])
                # Use pre-batched transform when available (single numpy op regardless of shell count).
                # Falls back to per-shell numpy when shells_batch is absent (old cache entries).
                shells_batch = nfp_data.get('shells_batch')
                if shells_batch is not None:
                    part_shells = _xform_shells_batched(shells_batch, placed_angle, cent.x, cent.y)
                else:
                    part_shells = _xform_shells_numpy(raw_shells, placed_angle, cent.x, cent.y)

                raw_holes = nfp_data.get('holes')  # None = not computed, [] = computed/empty
                # Holes are few; use full Shapely (needed for _discretize_edge later)
                part_holes = []
                for piece in (raw_holes or []):
                    r = rotate(piece, placed_angle, origin=(0, 0)) if abs(placed_angle) > 1e-9 else piece
                    part_holes.append(translate(r, xoff=cent.x, yoff=cent.y))

                per_part_nfps.append({'shells': part_shells, 'holes': part_holes})

                # Candidate points: discretize NFP shell boundary edges
                master = nfp_data.get('polygon')
                if master and not master.is_empty:
                    rotated_m = rotate(master, placed_angle, origin=(0, 0)) if abs(placed_angle) > 1e-9 else master
                    translated_m = translate(rotated_m, xoff=cent.x, yoff=cent.y)
                    points.extend(self._discretize_edge(translated_m.exterior))
                    for interior in translated_m.interiors:
                        points.extend(self._discretize_edge(interior))

                    # Best-effort union for global visualization ONLY
                    try:
                        if polygon.is_empty:
                            polygon = translated_m
                        else:
                            polygon = polygon.union(translated_m)
                    except Exception as e:
                        self.log(f"Visualization union failed (non-fatal): {e}")
                else:
                    # Vectorized candidate extraction from all shell edges.
                    # Collects all edge start/end coords in two numpy arrays (one Python
                    # iteration per shell just to gather coords — no per-edge computation),
                    # then samples midpoints in a single broadcast and deduplicates on a
                    # coarse grid to remove overlap from 1024+ nearly-identical shells.
                    if part_shells:
                        e_starts = np.concatenate([s.exterior.coords[:-1] for s in part_shells], axis=0)
                        e_ends   = np.concatenate([s.exterior.coords[1:]  for s in part_shells], axis=0)
                        # Sample start + midpoint of every edge (2 pts per edge)
                        mid = (e_starts + e_ends) * 0.5
                        pts_raw = np.concatenate([e_starts, mid], axis=0)
                        # Deduplicate on step_size grid — coarse enough to collapse the
                        # hundreds of nearly-identical shells, fine enough to keep quality
                        step = self.step_size
                        grid = max(1.0, step)
                        rounded = np.round(pts_raw / grid).astype(np.int32)
                        _, unique_idx = np.unique(rounded, axis=0, return_index=True)
                        pts_unique = pts_raw[unique_idx]
                        points.extend(Point(float(c[0]), float(c[1])) for c in pts_unique)

                # Add IFP void boundary edges as placement candidates (void nesting)
                for piece in part_holes:
                    points.extend(self._discretize_edge(piece.exterior))

                dt_xform = (time.perf_counter() - t_xform) * 1000
                if self.verbose and dt_xform > 20.0:
                    xform_path = "batched" if shells_batch is not None else "per-shell"
                    self.log(f"[PERF] NFP xform slow ({xform_path}): {placed_label}->{part_label} "
                             f"{len(part_shells)}shells {len(part_holes)}holes -> {dt_xform:.1f}ms")
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

        dt_total = (time.perf_counter() - t0_total) * 1000
        with self._perf_lock:
            self._perf_stats['cache_hits'] += n_hits
            self._perf_stats['cache_misses'] += n_misses
        if self.verbose and (n_misses > 0 or dt_total > 10.0):
            self.log(f"[PERF] get_global_nfp_for angle={angle:.1f} "
                     f"hits={n_hits} misses={n_misses} "
                     f"total={dt_total:.1f}ms candidates={len(points)}")
        return {'polygon': polygon, 'points': points, 'per_part_nfps': per_part_nfps}

    # Maximum exterior vertices to use when decomposing a shape for GPU NFP.
    # Triangulation produces O(N) triangles → O(N²) shell pairs for identical shapes.
    # 16 verts → ~32 shells for an O-with-hole (vs 1024 at 27 verts).
    # A small outward buffer (step_size/2) is applied after resampling to compensate
    # for the chord-to-arc inscribed-polygon approximation error that causes overlaps.
    _DECOMP_MAX_VERTS = 16

    @staticmethod
    def _resample_ring(ring, max_verts):
        """Resample a LinearRing to at most max_verts equally-spaced points."""
        n = len(ring.coords) - 1  # exclude closing coord
        if n <= max_verts:
            return list(ring.coords[:-1])
        length = ring.length
        step = length / max_verts
        pts = [ring.interpolate(i * step) for i in range(max_verts)]
        return [(p.x, p.y) for p in pts]

    def _resample_for_decomp(self, poly):
        """Return a simplified copy of poly with at most _DECOMP_MAX_VERTS per ring.

        Only applied when the polygon has more vertices than the cap — preserves
        the original when it's already small. Interior rings (holes) are also capped
        so the ring shape doesn't produce excess triangles along the inner boundary.

        After resampling, a small outward buffer is added to compensate for the
        chord-to-arc error: arc-length resampling produces an inscribed polygon
        (corners clipped inward), which underestimates the NFP exclusion zone and
        causes slight overlaps. The buffer expands the exclusion zone conservatively.
        """
        max_v = self._DECOMP_MAX_VERTS
        ext_n = len(poly.exterior.coords) - 1
        hole_ns = [len(h.coords) - 1 for h in poly.interiors]
        if ext_n <= max_v and all(n <= max_v for n in hole_ns):
            return poly  # already within cap
        new_ext = self._resample_ring(poly.exterior, max_v)
        new_ext.append(new_ext[0])  # close
        new_holes = []
        for interior in poly.interiors:
            pts = self._resample_ring(interior, max_v)
            pts.append(pts[0])
            new_holes.append(pts)
        result = Polygon(new_ext, new_holes)
        if not result.is_valid:
            result = result.buffer(0)
        # Outward buffer compensates for inscribed-polygon approximation error.
        # Use join_style=2 (mitre) to prevent Shapely's default round-corner arc
        # discretisation from inflating the vertex count (e.g. 16 verts → 77).
        # Mitre join adds zero extra vertices per convex corner, keeping the
        # polygon at ≤_DECOMP_MAX_VERTS so triangulation stays O(N) not O(N²).
        result = result.buffer(self.step_size * 0.5, join_style=2, mitre_limit=5.0)
        return result

    def _get_decomposition(self, shape):
        """Returns convex parts of the shape's original_polygon, centered at (0,0).

        The polygon is resampled to _DECOMP_MAX_VERTS before triangulation so that
        complex shapes (rings, circles) don't produce O(N²) shell pairs.
        """
        if not shape.original_polygon:
            return []
        shape_id = shape.source_freecad_object.Label
        with self._decomp_lock:
            if shape_id in self._decomp_cache:
                return self._decomp_cache[shape_id]
        master = shape.original_polygon
        cent = master.centroid
        centered = translate(master, -cent.x, -cent.y)
        resampled = self._resample_for_decomp(centered)
        orig_verts = len(centered.exterior.coords) - 1
        new_verts = len(resampled.exterior.coords) - 1
        if self.verbose and orig_verts != new_verts:
            self.log(f"[DECOMP] '{shape_id}': {orig_verts} → {new_verts} verts before triangulation")
        parts = minkowski_utils.decompose_if_needed(resampled, self.log)
        if self.verbose:
            self.log(f"[DECOMP] '{shape_id}': {len(parts)} convex parts")
        with self._decomp_lock:
            self._decomp_cache[shape_id] = parts
        return parts

    def precompute_nfp_batch(self, part_to_place, angles, sheet):
        """Pre-calculates all missing pairwise NFPs for a set of angles on the GPU.

        Two-pass approach for shapes with holes:
          Pass 1 (GPU): Exterior shells computed for ALL placed parts including holes.
                        Union is skipped for hole-shapes (visualization-only, expensive).
                        Stores entries with holes=None sentinel.
          Pass 2 (IFP): Fills in IFP for hole-shape entries via Shapely ThreadPoolExecutor.
                        Updates cache entries in-place; no full recompute.
        """
        if not self.use_gpu or not nfp_gpu_taichi:
            return

        missing_pairs = []
        part_to_place_label = part_to_place.source_freecad_object.Label

        for angle in angles:
            for p in sheet.parts:
                placed_label = p.shape.source_freecad_object.Label
                placed_angle = p.angle
                relative_angle = (angle - placed_angle) % 360.0
                if abs(relative_angle - 360.0) < 1e-5: relative_angle = 0.0
                relative_angle = round(relative_angle, 4)

                nfp_cache_key = (
                    placed_label, part_to_place_label, relative_angle,
                    part_to_place.spacing, part_to_place.deflection, part_to_place.simplification
                )

                if nfp_cache_key not in Shape.nfp_cache:
                    has_holes = bool(p.shape.original_polygon and list(p.shape.original_polygon.interiors))
                    missing_pairs.append({
                        'shape_A': p.shape,
                        'angle_B': relative_angle,
                        'key': nfp_cache_key,
                        'has_holes': has_holes,
                    })

        if self.verbose:
            self.log(f"[PERF] precompute_nfp_batch: {len(missing_pairs)} missing pairs "
                     f"({len(angles)} angles × {len(sheet.parts)} placed parts)")
        if not missing_pairs:
            return

        t0_batch = time.perf_counter()
        hole_fill_pairs = []  # Collected during Pass 1, processed in Pass 2

        try:
            poly_b_parts = self._get_decomposition(part_to_place)
            from shapely.affinity import scale
            parts_b_reflected = [scale(p, xfact=-1.0, yfact=-1.0, origin=(0,0)) for p in poly_b_parts]

            # Group missing pairs by shape_A label
            grouped_by_A = {}
            for m_pair in missing_pairs:
                shape_id = m_pair['shape_A'].source_freecad_object.Label
                if shape_id not in grouped_by_A:
                    grouped_by_A[shape_id] = {'shape': m_pair['shape_A'], 'missing': []}
                grouped_by_A[shape_id]['missing'].append(m_pair)

            # --- Pass 1: GPU batch (exterior shells for all placed parts) ---
            for shape_id, group in grouped_by_A.items():
                shape_A = group['shape']
                poly_A_parts = self._get_decomposition(shape_A)
                m_pairs = group['missing']
                angles_deg = sorted(list(set(p['angle_B'] for p in m_pairs)))
                has_holes = m_pairs[0]['has_holes']  # Same for all pairs of this shape_A

                if self.verbose:
                    self.log(f"GPU batch: {len(poly_A_parts)}x{len(parts_b_reflected)} pairs, {len(angles_deg)} angles")

                t0 = time.perf_counter()
                results_per_rotation = nfp_gpu_taichi.compute_nfp_batch(
                    poly_A_parts, parts_b_reflected, angles_deg
                )
                dt_gpu = (time.perf_counter() - t0) * 1000
                if self.verbose:
                    self.log(f"GPU batch compute: {dt_gpu:.1f}ms")

                angle_to_results = dict(zip(angles_deg, results_per_rotation))

                for m_pair in m_pairs:
                    angle = m_pair['angle_B']
                    cache_key = m_pair['key']
                    hulls = angle_to_results.get(angle, [])

                    if not hulls:
                        continue
                    try:
                        nfp_data = {
                            'shells': hulls,
                            'shells_batch': _make_shells_batch(hulls),
                            # holes=None: IFP pending Pass 2.  holes=[]: not applicable / empty.
                            'holes': None if has_holes else [],
                            'polygon': None,
                            'points': [],
                            'error': None
                        }
                        with Shape.nfp_cache_lock:
                            if cache_key not in Shape.nfp_cache:
                                Shape.nfp_cache[cache_key] = nfp_data

                        if has_holes:
                            hole_fill_pairs.append((shape_A, angle, part_to_place, cache_key))
                    except Exception as pair_err:
                        self.log(f"Skipping pair {cache_key}: {pair_err}")

            # --- Pass 2: IFP fill-in for hole-shape entries ---
            if hole_fill_pairs:
                self._fill_ifp_pass(hole_fill_pairs)

        except Exception as e:
            self.log(f"Batch NFP precompute error: {e}")
        dt_batch = (time.perf_counter() - t0_batch) * 1000
        if self.verbose:
            self.log(f"[PERF] precompute_nfp_batch total: {dt_batch:.1f}ms")

    def _fill_ifp_pass(self, hole_fill_pairs):
        """Pass 2: compute IFPs for hole-shape cache entries and update in-place.

        Args:
            hole_fill_pairs: list of (shape_A, angle_B, part_to_place, cache_key)
        """
        t0 = time.perf_counter()

        def _compute_one(args):
            shape_A, angle_B, part_to_place, cache_key = args
            try:
                nfp_holes = self._compute_ifp_for_hole_shape(shape_A, part_to_place, angle_B)
            except Exception as e:
                self.log(f"IFP fill error for {cache_key}: {e}")
                nfp_holes = []
            with Shape.nfp_cache_lock:
                entry = Shape.nfp_cache.get(cache_key)
                if entry is not None and entry.get('holes') is None:
                    entry['holes'] = nfp_holes

        n_workers = min(4, len(hole_fill_pairs))
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            list(executor.map(_compute_one, hole_fill_pairs))

        dt = (time.perf_counter() - t0) * 1000
        if self.verbose:
            self.log(f"[PERF] IFP fill-in: {len(hole_fill_pairs)} pairs in {dt:.1f}ms")

    def _compute_ifp_for_hole_shape(self, shape_A, part_to_place, angle_B):
        """Compute IFP convex parts for a placed shape with interior rings (holes).

        Pure Shapely — no GPU. Safe to call from a thread pool.

        Returns:
            list[Polygon]: convex decomposition of all IFPs, or [] if part doesn't fit.
        """
        nfp_holes = []
        mB = part_to_place.original_polygon
        cB = mB.centroid
        B_centered = translate(mB, -cB.x, -cB.y)
        B_rot = rotate(B_centered, angle_B, origin=(0, 0))
        mA = shape_A.original_polygon
        cA = mA.centroid
        A_centered = translate(mA, -cA.x, -cA.y)
        for hole in A_centered.interiors:
            hole_poly = Polygon(hole.coords)
            if (B_rot.bounds[2] - B_rot.bounds[0] < hole_poly.bounds[2] - hole_poly.bounds[0] and
                    B_rot.bounds[3] - B_rot.bounds[1] < hole_poly.bounds[3] - hole_poly.bounds[1] and
                    B_rot.area < hole_poly.area):
                ifp = minkowski_utils.calculate_inner_fit_polygon(
                    hole_poly, 0, B_centered, angle_B, self.log
                )
                if ifp and not ifp.is_empty:
                    nfp_holes.extend(minkowski_utils.decompose_if_needed(ifp, self.log))
        return nfp_holes

    def score_candidates_gpu(self, part_to_place, rotation_candidates):
        """Calculates scores for multiple candidates using GPU PIP scoring.

        rotation_candidates: list of (angle, points, nfp_entry) tuples.
        nfp_entry is the dict already returned by get_global_nfp_for — do NOT
        call get_global_nfp_for again here.
        """
        if not self.use_gpu or not nfp_gpu_taichi:
             return None

        import numpy as np
        best_overall = {'metric': float('inf')}
        dir_x, dir_y = self.search_direction
        t0_score = time.perf_counter()
        total_candidates = sum(len(pts) for _, pts, _ in rotation_candidates)
        if self.verbose:
            self.log(f"[PERF] score_candidates_gpu: {len(rotation_candidates)} angles, "
                     f"{total_candidates} total candidates")

        for angle, points, nfp_entry in rotation_candidates:
            
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
            
            n_scored = 0
            for i, pt in enumerate(points):
                if results[i] == 1: continue # NFP collision
                if bounds_results[i] == 0: continue # Out of bounds
                
                # If we're here, it passed both GPU checks
                metric = pt.x * (-dir_x) + pt.y * (-dir_y)
                if metric < best_overall['metric']:
                    best_overall = {'x': pt.x, 'y': pt.y, 'angle': angle, 'metric': metric}
                n_scored += 1
            
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
            nfp_data = {"polygon": master_nfp} if master_nfp else {}
        except Exception as e:
            self.log(f"Error calculating NFP for {cache_key}: {e}")
            nfp_data = {'error': str(e)}
        with Shape.nfp_cache_lock: Shape.nfp_cache[cache_key] = nfp_data
        return nfp_data

    def _calculate_and_cache_nfp_gpu(self, shape_A, angle_A, part_to_place, angle_B, cache_key):
        with Shape.nfp_cache_lock:
            cached_nfp_data = Shape.nfp_cache.get(cache_key)
            if cached_nfp_data: return cached_nfp_data
        try:
            poly_A_parts = self._get_decomposition(shape_A)
            poly_B_parts = self._get_decomposition(part_to_place)
            from shapely.affinity import scale
            parts_b_reflected = [scale(p, xfact=-1.0, yfact=-1.0, origin=(0,0)) for p in poly_B_parts]
            pairs = []
            rel_angle_rad = math.radians(angle_B)
            for pA in poly_A_parts:
                for pB in parts_b_reflected:
                    pairs.append((pA, pB, rel_angle_rad))
            
            # GPU-006: Timing
            t0 = time.perf_counter()
            hulls = nfp_gpu_taichi.compute_nfp_pairs(pairs)
            dt_gpu = (time.perf_counter() - t0) * 1000
            if self.verbose:
                self.log(f"GPU NFP pairs ({len(pairs)} pairs): {dt_gpu:.1f}ms")
                
            valid_hulls = [h for h in hulls if h is not None]
            if not valid_hulls: return None
            
            # GPU-007: No-Union data structure
            nfp_shells = valid_hulls
            nfp_holes = (self._compute_ifp_for_hole_shape(shape_A, part_to_place, angle_B)
                         if shape_A.original_polygon.interiors else [])
            
            nfp_data = {
                "shells": nfp_shells,
                "shells_batch": _make_shells_batch(nfp_shells),
                "holes": nfp_holes,
                "polygon": None
            }
        except Exception as e:
            self.log(f"GPU NFP Error for {cache_key}: {e}. Falling back to CPU.")
            return self._calculate_and_cache_nfp(shape_A, angle_A, part_to_place, angle_B, cache_key)
        
        with Shape.nfp_cache_lock: Shape.nfp_cache[cache_key] = nfp_data
        return nfp_data

    def get_perf_stats(self):
        with self._perf_lock:
            return dict(self._perf_stats)

    def reset_perf_stats(self):
        with self._perf_lock:
            self._perf_stats = {'cache_hits': 0, 'cache_misses': 0, 'nfp_compute_ms': 0.0}

    def _discretize_edge(self, line):
        points = [Point(line.coords[0])]
        length = line.length
        if length > self.step_size:
            num_segments = int(length / self.step_size)
            for i in range(1, num_segments):
                points.append(line.interpolate(float(i) / num_segments, normalized=True))
        points.append(Point(line.coords[-1]))
        return points
