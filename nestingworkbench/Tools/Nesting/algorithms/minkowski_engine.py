
import math
import time
import FreeCAD
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from shapely.geometry import Polygon, Point, MultiPoint
from shapely.affinity import translate, rotate
from shapely.ops import unary_union
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

    def log(self, message):
        if self.log_callback:
            with self._log_lock:
                self.log_callback("MINKOWSKI_ENGINE: " + message)
        else:
             import FreeCAD
             FreeCAD.Console.PrintMessage(f"MINKOWSKI_ENGINE: {message}\n")

    def get_global_nfp_for(self, part_to_place, angle, sheet):
        """
        Calculates (incrementally) the total forbidden area (Union of NFPs) 
        for a specific part rotation on the sheet.
        """
        cache_key = (part_to_place.source_freecad_object.Label, round(angle, 4))
        
        with sheet.nfp_cache_lock:
            if cache_key not in sheet.nfp_cache:
                sheet.nfp_cache[cache_key] = {
                    'polygon': Polygon(), # Start empty
                    'last_part_idx': 0,
                    'points': [],
                    'prepared': None,
                    'convex_pieces': [] # GPU-002: Store individual pieces
                }
            entry = sheet.nfp_cache[cache_key]
            target_idx = len(sheet.parts)
            if entry['last_part_idx'] >= target_idx:
                return entry
            start_idx = entry['last_part_idx']
            parts_to_process = sheet.parts[start_idx:target_idx]

        new_polys = []
        part_to_place_master_label = part_to_place.source_freecad_object.Label
        
        for p in parts_to_process:
            placed_label = p.shape.source_freecad_object.Label
            placed_angle = p.angle
            
            relative_angle = (angle - placed_angle) % 360.0
            if abs(relative_angle - 360.0) < 1e-5: relative_angle = 0.0
            relative_angle = round(relative_angle, 4)
            
            nfp_cache_key = (
                placed_label, 
                part_to_place_master_label, 
                relative_angle, 
                part_to_place.spacing,
                part_to_place.deflection,
                part_to_place.simplification
            )
            
            with Shape.nfp_cache_lock:
                nfp_data = Shape.nfp_cache.get(nfp_cache_key)
            if not nfp_data:
                if self.use_gpu:
                    nfp_data = self._calculate_and_cache_nfp_gpu(
                        p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                    )
                else:
                    nfp_data = self._calculate_and_cache_nfp(
                        p.shape, 0.0, part_to_place, relative_angle, nfp_cache_key
                    )
            
            if nfp_data and nfp_data.get('error'):
                self.log(f"Skipping rotation due to NFP error: {nfp_data['error']}")
                return None

            if nfp_data and nfp_data.get('polygon'):
                master = nfp_data['polygon']
                rotated = rotate(master, placed_angle, origin=(0, 0))
                cent = p.shape.centroid
                translated = translate(rotated, xoff=cent.x, yoff=cent.y)
                new_polys.append(translated)
        
        with sheet.nfp_cache_lock:
            if new_polys:
                if self.use_gpu:
                    # GPU-002: Use exact union for visualization, but keep individual hulls for GPU scoring
                    batch_union = unary_union(new_polys)
                    if entry['polygon'].is_empty:
                        entry['polygon'] = batch_union
                    else:
                        entry['polygon'] = entry['polygon'].union(batch_union)
                    
                    if 'convex_pieces' not in entry:
                        entry['convex_pieces'] = []
                    entry['convex_pieces'].extend(new_polys)
                else:
                    batch_union = unary_union(new_polys)
                    if entry['polygon'].is_empty:
                        entry['polygon'] = batch_union
                    else:
                        entry['polygon'] = entry['polygon'].union(batch_union)

                if not entry['polygon'].is_valid:
                    entry['polygon'] = entry['polygon'].buffer(0)

                points = []
                if not entry['polygon'].is_empty:
                    polys = [entry['polygon']] if entry['polygon'].geom_type == 'Polygon' else entry['polygon'].geoms
                    for poly in polys:
                         if poly.geom_type == 'Polygon':
                             points.extend(self._discretize_edge(poly.exterior))
                             for interior in poly.interiors:
                                 points.extend(self._discretize_edge(interior))
                entry['points'] = points
                entry['prepared'] = None
            entry['last_part_idx'] = target_idx
        return entry

    def _get_decomposition(self, shape):
        """Returns convex parts of the shape's original_polygon, centered at (0,0)."""
        if not shape.original_polygon:
            return []
        shape_id = shape.source_freecad_object.Label
        with self._decomp_lock:
            if shape_id in self._decomp_cache:
                return self._decomp_cache[shape_id]
        master = shape.original_polygon
        cent = master.centroid
        centered = translate(master, -cent.x, -cent.y)
        parts = minkowski_utils.decompose_if_needed(centered, self.log)
        with self._decomp_lock:
            self._decomp_cache[shape_id] = parts
        return parts

    def precompute_nfp_batch(self, part_to_place, angles, sheet):
        """Pre-calculates all missing pairwise NFPs for a set of angles on the GPU."""
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
                
                with Shape.nfp_cache_lock:
                    if nfp_cache_key not in Shape.nfp_cache:
                        missing_pairs.append({'shape_A': p.shape, 'angle_B': relative_angle, 'key': nfp_cache_key})
        
        if not missing_pairs:
            return

        try:
            poly_b_parts = self._get_decomposition(part_to_place)
            from shapely.affinity import scale
            parts_b_reflected = [scale(p, xfact=-1.0, yfact=-1.0, origin=(0,0)) for p in poly_b_parts]
            
            # Group missing pairs by shape_A to use compute_nfp_batch effectively
            grouped_by_A = {}
            for m_pair in missing_pairs:
                shape_id = m_pair['shape_A'].source_freecad_object.Label
                if shape_id not in grouped_by_A:
                    grouped_by_A[shape_id] = {'shape': m_pair['shape_A'], 'missing': []}
                grouped_by_A[shape_id]['missing'].append(m_pair)
            
            for shape_id, group in grouped_by_A.items():
                shape_A = group['shape']
                poly_A_parts = self._get_decomposition(shape_A)
                
                # Unique angles for this A
                m_pairs = group['missing']
                angles_deg = sorted(list(set(p['angle_B'] for p in m_pairs)))
                
                if self.verbose:
                    self.log(f"GPU batch: {len(poly_A_parts)}x{len(parts_b_reflected)} pairs, {len(angles_deg)} angles")
                
                # GPU-006: Timing
                t0 = time.perf_counter()
                
                # GPU-004: Compute all NFPs for this A-B pair across all angles
                results_per_rotation = nfp_gpu_taichi.compute_nfp_batch(
                    poly_A_parts, parts_b_reflected, angles_deg
                )
                
                dt_gpu = (time.perf_counter() - t0) * 1000
                if self.verbose:
                    self.log(f"GPU batch compute: {dt_gpu:.1f}ms")
                
                t_union = 0
                # Map results back to cache keys
                angle_to_results = dict(zip(angles_deg, results_per_rotation))
                
                for m_pair in m_pairs:
                    angle = m_pair['angle_B']
                    cache_key = m_pair['key']
                    hulls = angle_to_results.get(angle, [])
                    
                    if hulls:
                        t_u0 = time.perf_counter()
                        # GPU-003: GPU Union (conservative approximation)
                        union_poly = nfp_gpu_taichi.union_convex_hulls_gpu(hulls)
                        if union_poly is None:
                            # Fallback to CPU
                            if self.verbose:
                                FreeCAD.Console.PrintLog("[MinkowskiEngine] GPU batch union fallback to CPU\n")
                            union_poly = unary_union(hulls)
                        t_union += (time.perf_counter() - t_u0) * 1000

                        if not union_poly.is_valid:
                            union_poly = union_poly.buffer(0)
                        
                        nfp_data = {'polygon': union_poly, 'points': [], 'error': None}
                        with Shape.nfp_cache_lock:
                            if cache_key not in Shape.nfp_cache:
                                Shape.nfp_cache[cache_key] = nfp_data
                                
                if self.verbose and t_union > 0:
                    self.log(f"GPU batch union total: {t_union:.1f}ms")
        except Exception as e:
            self.log(f"Batch NFP precompute error: {e}")

    def score_candidates_gpu(self, part_to_place, rotation_candidates, sheet):
        """Calculates scores for multiple candidates using GPU PIP scoring."""
        if not self.use_gpu or not nfp_gpu_taichi:
             return None
             
        import numpy as np
        best_overall = {'metric': float('inf')}
        dir_x, dir_y = self.search_direction

        for angle, points in rotation_candidates:
            nfp_entry = self.get_global_nfp_for(part_to_place, angle, sheet)
            
            # GPU-002: Use pre-collected individual convex pieces
            convex_nfps = nfp_entry.get('convex_pieces', [])
            
            # If for some reason we don't have pieces (e.g. legacy cache), fallback to decomposition
            if not convex_nfps and not nfp_entry['polygon'].is_empty:
                poly_union = nfp_entry['polygon']
                if poly_union.geom_type == 'Polygon':
                    convex_nfps = minkowski_utils.decompose_if_needed(poly_union, self.log)
                elif poly_union.geom_type == 'MultiPolygon':
                    convex_nfps = []
                    for p in poly_union.geoms:
                        convex_nfps.extend(minkowski_utils.decompose_if_needed(p, self.log))

            pts_np = np.array([[p.x, p.y] for p in points], dtype=np.float32)
            results = nfp_gpu_taichi.compute_batch_pip(pts_np, convex_nfps) if convex_nfps else np.zeros(len(points), dtype=np.int32)
            
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
            
            # GPU-003: GPU Union (conservative approximation)
            nfp_exterior_poly = None
            if valid_hulls:
                t_u0 = time.perf_counter()
                nfp_exterior_poly = nfp_gpu_taichi.union_convex_hulls_gpu(valid_hulls)
                if nfp_exterior_poly is None:
                    # Fallback to CPU
                    if self.verbose:
                        FreeCAD.Console.PrintLog("[MinkowskiEngine] GPU union fallback to CPU\n")
                    nfp_exterior_poly = unary_union(valid_hulls)
                dt_union = (time.perf_counter() - t_u0) * 1000
                if self.verbose:
                    self.log(f"GPU NFP union: {dt_union:.1f}ms")

            if nfp_exterior_poly and not nfp_exterior_poly.is_valid: 
                nfp_exterior_poly = nfp_exterior_poly.buffer(0)
            if not nfp_exterior_poly or nfp_exterior_poly.is_empty: return None

            nfp_interiors = []
            if shape_A.original_polygon.interiors:
                mB = part_to_place.original_polygon
                cB = mB.centroid
                B_centered = translate(mB, -cB.x, -cB.y)
                B_rot = rotate(B_centered, angle_B, origin=(0,0))
                mA = shape_A.original_polygon
                cA = mA.centroid
                A_centered = translate(mA, -cA.x, -cA.y)
                for hole in A_centered.interiors:
                    hole_poly = Polygon(hole.coords)
                    if (B_rot.bounds[2] - B_rot.bounds[0] < hole_poly.bounds[2] - hole_poly.bounds[0] and
                        B_rot.bounds[3] - B_rot.bounds[1] < hole_poly.bounds[3] - hole_poly.bounds[1] and
                        B_rot.area < hole_poly.area):
                        ifp = minkowski_utils.calculate_inner_fit_polygon(hole_poly, 0, B_centered, angle_B, self.log)
                        if ifp and not ifp.is_empty:
                            if ifp.geom_type == 'Polygon': nfp_interiors.append(ifp.exterior)
                            elif ifp.geom_type == 'MultiPolygon':
                                for p in ifp.geoms: nfp_interiors.append(p.exterior)
            master_nfp = Polygon(nfp_exterior_poly.exterior, nfp_interiors) if nfp_exterior_poly else None
            nfp_data = {"polygon": master_nfp} if master_nfp else {}
        except Exception as e:
            self.log(f"GPU NFP Error for {cache_key}: {e}. Falling back to CPU.")
            return self._calculate_and_cache_nfp(shape_A, angle_A, part_to_place, angle_B, cache_key)
        with Shape.nfp_cache_lock: Shape.nfp_cache[cache_key] = nfp_data
        return nfp_data

    def _discretize_edge(self, line):
        points = [Point(line.coords[0])]
        length = line.length
        if length > self.step_size:
            num_segments = int(length / self.step_size)
            for i in range(1, num_segments):
                points.append(line.interpolate(float(i) / num_segments, normalized=True))
        points.append(Point(line.coords[-1]))
        return points
