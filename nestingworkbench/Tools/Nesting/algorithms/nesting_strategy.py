
import math
import os
import random
import copy
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from shapely.geometry import Polygon, Point

from shapely.prepared import prep
from shapely.affinity import rotate, translate

import FreeCAD
from ....datatypes.sheet import Sheet
from ....datatypes.placed_part import PlacedPart
from . import genetic_utils
from .minkowski_engine import MinkowskiEngine

class PlacementOptimizer:
    """
    Handles the geometric logic of finding the best position for a part on a sheet.
    """
    def __init__(self, engine, rotation_steps, search_direction, log_callback=None, trial_callback=None):
        self.engine = engine
        self.rotation_steps = max(1, rotation_steps)
        self.search_direction = search_direction
        self.log_callback = log_callback
        self.trial_callback = trial_callback  # Called for each trial placement in simulation mode
        self.verbose = False

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def find_best_placement(self, part, sheet):
        """
        Parallel evaluation of rotations to find best spot.
        """
        if part.original_polygon is None and part.polygon is not None:
            part.original_polygon = part.polygon
            
        # Pre-group placed parts by (master_label, angle)
        placed_parts_grouped = defaultdict(list)
        for p in sheet.parts:
            key = (p.shape.source_freecad_object.Label, p.angle)
            placed_parts_grouped[key].append(p)
            
        direction = self.search_direction
        if direction is None:
             angle_rad = random.uniform(0, 2 * math.pi)
             direction = (math.cos(angle_rad), math.sin(angle_rad))

        best_result = {'metric': float('inf')}
        
        # Use per-part rotation_steps if available, otherwise use global
        part_rotation_steps = getattr(part, 'rotation_steps', None)
        if part_rotation_steps is None or part_rotation_steps < 1:
            part_rotation_steps = self.rotation_steps
        part_rotation_steps = max(1, part_rotation_steps)
        
        # Batch evaluate or parallel evaluate
        if self.engine.use_gpu:
            import time as _time
            t0_fbp = _time.perf_counter()
            # 1. Collect candidates for ALL rotations
            all_rotation_candidates = []
            angles = [i * (360.0 / part_rotation_steps) for i in range(part_rotation_steps)]

            # Precompute NFPs in batch on GPU
            t0_pre = _time.perf_counter()
            self.engine.precompute_nfp_batch(part, angles, sheet)
            dt_pre = (_time.perf_counter() - t0_pre) * 1000

            t0_nfp = _time.perf_counter()
            for angle in angles:
                # Call get_global_nfp_for ONCE and pass it to both helpers
                nfp_entry = self.engine.get_global_nfp_for(part, angle, sheet)
                if nfp_entry is None:
                    continue
                candidates = self._get_candidates_for_rotation(angle, part, sheet, nfp_entry=nfp_entry)
                if len(candidates):
                    all_rotation_candidates.append((angle, candidates, nfp_entry))
            dt_nfp = (_time.perf_counter() - t0_nfp) * 1000
            self.log(f"[PERF] find_best_placement '{getattr(part, 'id', '?')}': "
                     f"precompute={dt_pre:.0f}ms nfp_assembly={dt_nfp:.0f}ms "
                     f"(placed={len(sheet.parts)} angles={len(angles)})")

            # 2. Batch score on GPU
            res = self.engine.score_candidates_gpu(part, all_rotation_candidates)
            if res and res.get('metric', float('inf')) < best_result['metric']:
                best_result = res
                # BUG-003: Restore visual feedback for GPU path
                if self.trial_callback and best_result.get('x') is not None:
                     self.trial_callback(part, best_result['angle'], best_result['x'], best_result['y'])
        else:
            # CPU Parallel evaluation
            import time as _time
            t0_parallel = _time.perf_counter()
            total_nfp_ms = 0.0
            total_score_ms = 0.0
            with ThreadPoolExecutor() as executor:
                angles = [i * (360.0 / part_rotation_steps) for i in range(part_rotation_steps)]
                futures = {
                    executor.submit(self._evaluate_rotation, angle, part, placed_parts_grouped, sheet, direction): angle
                    for angle in angles
                }

                for future in as_completed(futures):
                    try:
                        res = future.result()
                        if res:
                            total_nfp_ms += res.get('_t_nfp_ms', 0)
                            total_score_ms += res.get('_t_score_ms', 0)
                            if res['metric'] < best_result['metric']:
                                best_result = res
                                # Call trial callback from main thread for each better result found
                                if self.trial_callback and best_result.get('x') is not None:
                                    self.trial_callback(part, best_result['angle'], best_result['x'], best_result['y'])
                    except Exception as e:
                        self.log(f"Error in rotation evaluation thread: {e}")

            dt_parallel = (_time.perf_counter() - t0_parallel) * 1000
            self.log(f"[TIMING] '{getattr(part, 'id', '?')}': wall={dt_parallel:.0f}ms "
                     f"nfp={total_nfp_ms:.0f}ms score={total_score_ms:.0f}ms "
                     f"({len(angles)} rotations, {len(sheet.parts)} placed)")
            if self.verbose:
                self.log(f"  -> Parallel eval: {len(angles)} rotations in {dt_parallel:.1f}ms "
                         f"(ideal speedup: {len(angles)}x, pool workers: {min(len(angles), os.cpu_count() or 1)})")
            best_result['_t_nfp_ms'] = total_nfp_ms
            best_result['_t_score_ms'] = total_score_ms
        
        if self.verbose:
            self.log(f"  -> Best result for {part.id}: {best_result}")

        if best_result.get('x') is not None:
             part.set_rotation(best_result['angle'], reposition=False)
             curr = part.centroid
             part.move(best_result['x'] - curr.x, best_result['y'] - curr.y)
             return part
        return None

    def _evaluate_rotation(self, angle, part, placed_parts_grouped, sheet, direction):
        import time as _time, threading
        t0 = _time.perf_counter()
        thread_id = threading.current_thread().name
        
        # 1. Get Combined NFP from Engine (Incrementally Cached on Sheet)
        nfp_entry = self.engine.get_global_nfp_for(part, angle, sheet)
        t_nfp = _time.perf_counter()
        
        # Check for NFP calculation failure
        if nfp_entry is None:
            return {'metric': float('inf')}
        
        bin_polygon = self.engine.bin_polygon

        # Prepare geometry for fast containment check
        union_poly = nfp_entry['polygon']
        prepared_nfp = prep(union_poly) if not union_poly.is_empty else None

        # 2. Generate Candidates — pass the already-computed nfp_entry to avoid a second call
        ext_cands = self._get_candidates_for_rotation(angle, part, sheet, nfp_entry=nfp_entry)
        if not len(ext_cands):
            return {'metric': float('inf')}

        rotated_poly = rotate(part.original_polygon, angle, origin='centroid')
        if not rotated_poly: return {'metric': float('inf')}

        # 3. Score Candidates
        best = {'metric': float('inf')}
        rejected_nfp = 0
        rejected_bounds = 0

        centroid = rotated_poly.centroid

        valid_rows = []
        for row in ext_cands:
            x, y = float(row[0]), float(row[1])
            if prepared_nfp and prepared_nfp.contains(Point(x, y)):
                rejected_nfp += 1
                continue
            dx, dy = x - centroid.x, y - centroid.y
            if not bin_polygon.contains(translate(rotated_poly, xoff=dx, yoff=dy)):
                rejected_bounds += 1
                continue
            valid_rows.append((x, y))

        if valid_rows:
            pts_arr = np.array(valid_rows, dtype=np.float64)
            valid_mask = np.ones(len(valid_rows), dtype=bool)
            best_idx, metric = MinkowskiEngine.score_gravity(pts_arr, valid_mask, direction)
            if best_idx is not None:
                best = {'x': pts_arr[best_idx, 0], 'y': pts_arr[best_idx, 1],
                        'angle': angle, 'metric': metric}
        
        # Notify better result found
        if self.trial_callback and best.get('x') is not None:
             self.trial_callback(part, angle, best['x'], best['y'])

        t_end = _time.perf_counter()
        if self.verbose:
            self.log(f"    [{thread_id}] angle={angle:.0f}: NFP={((t_nfp-t0)*1000):.1f}ms, "
                     f"score={((t_end-t_nfp)*1000):.1f}ms, total={((t_end-t0)*1000):.1f}ms")

        best['_t_nfp_ms'] = (t_nfp - t0) * 1000
        best['_t_score_ms'] = (t_end - t_nfp) * 1000
        return best

    def _get_candidates_for_rotation(self, angle, part, sheet, nfp_entry=None):
        """Helper to compute candidate points for a specific rotation.

        Pass a pre-computed nfp_entry to avoid a redundant get_global_nfp_for call.
        Returns (N, 2) float32 numpy array.
        """
        if nfp_entry is None:
            nfp_entry = self.engine.get_global_nfp_for(part, angle, sheet)
        if nfp_entry is None:
            return np.empty((0, 2), dtype=np.float32)

        rotated_poly = rotate(part.original_polygon, angle, origin='centroid')
        if not rotated_poly:
            return np.empty((0, 2), dtype=np.float32)

        min_x, min_y, max_x, max_y = rotated_poly.bounds
        w_bin, h_bin = self.engine.bin_width, self.engine.bin_height

        corners = np.array([
            [-min_x,        -min_y       ],
            [w_bin - max_x, -min_y       ],
            [-min_x,        h_bin - max_y],
            [w_bin - max_x, h_bin - max_y],
        ], dtype=np.float32)

        nfp_pts = nfp_entry['points']  # (N, 2) float32
        if len(nfp_pts):
            mask = ((nfp_pts[:, 0] >= 0) & (nfp_pts[:, 0] <= w_bin) &
                    (nfp_pts[:, 1] >= 0) & (nfp_pts[:, 1] <= h_bin))
            filtered = nfp_pts[mask]
            return np.vstack([corners, filtered]) if len(filtered) else corners
        return corners


class Nester:
    """
    The main nesting algorithm class. 
    It orchestrates the nesting process using PlacementOptimizer and MinkowskiEngine.
    """
    def __init__(self, width, height, rotation_steps=1, **kwargs):
        self.bin_width = width
        self.bin_height = height
        self.spacing = kwargs.get("spacing", 0)
        self.search_direction = kwargs.get("search_direction", (0, -1)) # Default Down
        
        # Optimization settings (kept for backwards compatibility, GA now in controller)
        self.population_size = kwargs.get("population_size", 1)
        self.generations = kwargs.get("generations", 1)
        self.mutation_rate = 0.1
        self.elite_size = max(1, int(self.population_size * 0.1))
        
        # Logging control
        self.quiet = kwargs.get("quiet", False)  # If True, suppress per-part logs
        self.verbose = kwargs.get("verbose", False)  # If True, enable extra detailed logs
        self.log_callback = kwargs.get("log_callback")
        self.trial_callback = kwargs.get("trial_callback")  # For visualizing trial placements
        self.part_start_callback = kwargs.get("part_start_callback")  # Called when starting to place a part
        self.part_end_callback = kwargs.get("part_end_callback")  # Called after part is placed
        self.progress_callback = kwargs.get("progress_callback") # Called with (current, total)
        self.cancel_callback = kwargs.get("cancel_callback") # Called to check if nesting should abort
        
        step_size = kwargs.get("step_size", 5.0) 
        use_gpu = kwargs.get("use_gpu", False)
        self.engine = MinkowskiEngine(width, height, step_size, log_callback=self.log_callback, use_gpu=use_gpu, verbose=self.verbose, search_direction=self.search_direction)
        self.optimizer = PlacementOptimizer(self.engine, rotation_steps, self.search_direction, self.log_callback, self.trial_callback)
        self.optimizer.verbose = self.verbose

        self.parts_to_place = []
        self.sheets = []
        self.update_callback = None # Can be set externally

        # Background NFP pre-computation
        self._precompute_pool = ThreadPoolExecutor(max_workers=os.cpu_count())
        self._precomputed_keys = set()

    def log(self, message, level="message"):
        if self.log_callback:
            self.log_callback(message)
        else:
            if level == "warning":
                FreeCAD.Console.PrintWarning(f"NESTER: {message}\n")
            else:
                FreeCAD.Console.PrintMessage(f"NESTER: {message}\n")

    def nest(self, parts, sort=True):
        """
        Main entry point for nesting.

        NOTE: GA optimization is now handled at the controller level using LayoutManager.
        This method just runs standard greedy nesting.
        """
        # Cleanup debug objects — only safe from the main thread
        try:
            from PySide.QtCore import QThread, QCoreApplication
            app = QCoreApplication.instance()
            if app and QThread.currentThread() == app.thread():
                doc = FreeCAD.ActiveDocument
                if doc and doc.getObject("MinkowskiDebug"):
                    doc.removeObject("MinkowskiDebug")
                    doc.recompute()
        except Exception:
            pass

        return self._nest_standard(parts, sort=sort)

    def _nest_standard(self, parts, sort=True, quiet=None):
        """
        Standard greedy nesting strategy.
        
        Args:
            parts: List of parts to nest
            sort: Whether to sort by area (largest first)
            quiet: If True, suppresses logging and callbacks. Defaults to self.quiet.
        """
        # Use instance quiet setting if not explicitly passed
        if quiet is None:
            quiet = self.quiet
        current_parts = list(parts)
        if sort:
            current_parts.sort(key=lambda p: p.area, reverse=True)

        sheets = []
        unplaced_parts = []
        total_parts = len(current_parts)
        _part_timings = []  # (part_id, elapsed_s, placed)
        self.engine.reset_perf_stats()

        for i, part in enumerate(current_parts):
            if self.cancel_callback and self.cancel_callback():
                self.log("Nesting cancelled by user.")
                break

            if self.verbose and not quiet:
                self.log(f"Processing part {i+1}/{total_parts}: {part.id}")
            
            if not quiet and self.progress_callback:
                self.progress_callback(i + 1, total_parts, f"Placing {part.id}...")
            
            import time as _time
            _t0_part = _time.perf_counter()
            start_part_time = datetime.now()
            placed = False

            # Notify start of part placement (for highlighting master shapes)
            if not quiet and self.part_start_callback:
                self.part_start_callback(part)

            # 1. Try existing sheets
            for sheet_idx, sheet in enumerate(sheets):
                if (sheet.width * sheet.height - sheet.used_area) < part.area: continue

                if self._attempt_placement_on_sheet(part, sheet):
                    placed = True
                    if self.verbose and not quiet:
                        elapsed = (datetime.now() - start_part_time).total_seconds()
                        self.log(f"  -> Placed on Sheet {sheet_idx+1} ({elapsed:.4f}s)")

                    if not quiet and self.update_callback:
                        self.update_callback(part, sheet)
                    break

            # 2. Try new sheet
            if not placed:
                new_sheet = Sheet(len(sheets), self.bin_width, self.bin_height, spacing=self.spacing)
                if self._attempt_placement_on_sheet(part, new_sheet):
                    sheets.append(new_sheet)
                    placed = True
                    if self.verbose and not quiet:
                        elapsed = (datetime.now() - start_part_time).total_seconds()
                        self.log(f"  -> Placed on New Sheet {len(sheets)} ({elapsed:.4f}s)")

                    if not quiet and self.update_callback:
                        self.update_callback(part, new_sheet)
                else:
                    unplaced_parts.append(part)
                    if not quiet:
                        self.log(f"  -> FAILED to place in {(datetime.now() - start_part_time).total_seconds():.4f}s")

            _part_timings.append((part.id, _time.perf_counter() - _t0_part, placed))

            # Notify end of part placement (for unhighlighting master shapes)
            if not quiet and self.part_end_callback:
                self.part_end_callback(part, placed)

            # Submit background NFP pre-computation for remaining parts.
            # GPU mode: skip — precompute_nfp_batch() already handles this via a single
            # batched kernel call at the start of each find_best_placement. Background
            # per-pair tasks would compete for _kernel_lock and slow the foreground down.
            if placed and i < total_parts - 1 and not self.engine.use_gpu:
                self._submit_precomputation(sheets, current_parts[i+1:])

        # Shut down precompute pool (don't wait for pending futures)
        self._precompute_pool.shutdown(wait=False)
        self._precomputed_keys.clear()

        if not quiet and _part_timings:
            self._log_timing_summary(_part_timings)

        return sheets, unplaced_parts

    def _log_timing_summary(self, part_timings):
        total_s = sum(t for _, t, _ in part_timings)
        cache = self.engine.get_perf_stats()
        total_lookups = cache['cache_hits'] + cache['cache_misses']
        hit_pct = cache['cache_hits'] / total_lookups * 100 if total_lookups else 0
        self.log(
            f"[TIMING] {len(part_timings)} parts in {total_s:.2f}s | "
            f"NFP cache: {cache['cache_hits']} hits ({hit_pct:.0f}%) / "
            f"{cache['cache_misses']} misses, compute={cache['nfp_compute_ms']:.0f}ms"
        )
        slowest = sorted(part_timings, key=lambda x: -x[1])[:5]
        self.log("[TIMING] Slowest: " + ", ".join(
            f"{pid}={t:.2f}s{'(unplaced)' if not ok else ''}" for pid, t, ok in slowest
        ))

    def _attempt_placement_on_sheet(self, part, sheet):
        """Delegates to PlacementOptimizer."""
        placed_part = self.optimizer.find_best_placement(part, sheet)
        
        if placed_part:
            # We trust the PlacementOptimizer (and NFP engine) to have found a valid spot.
            placed_part.placement = placed_part.get_final_placement(sheet.get_origin())
            new_placed_part = PlacedPart(placed_part)
            sheet.add_part(new_placed_part)
            return True
        return False

    def _submit_precomputation(self, sheets, remaining_parts):
        """Submit background NFP computations for remaining parts against all placed parts.
        
        While the main thread is placing the current part, background threads
        compute master NFPs that will be needed for future parts. When those
        parts are actually placed, their NFPs are already cached.
        """
        from ....datatypes.shape import Shape
        
        # Collect all placed parts across all sheets
        placed_parts = []
        for sheet in sheets:
            for pp in sheet.parts:
                placed_parts.append(pp)
        
        if not placed_parts:
            return
        
        for remaining in remaining_parts:
            # Per-part rotation steps
            rot_steps = getattr(remaining, 'rotation_steps', None)
            if rot_steps is None or rot_steps < 1:
                rot_steps = self.optimizer.rotation_steps
            rot_steps = max(1, rot_steps)
            angles = [i * (360.0 / rot_steps) for i in range(rot_steps)]
            
            for placed in placed_parts:
                for angle in angles:
                    relative_angle = (angle - placed.angle) % 360.0
                    if abs(relative_angle - 360.0) < 1e-5:
                        relative_angle = 0.0
                    relative_angle = round(relative_angle, 4)
                    
                    cache_key = (
                        placed.shape.source_freecad_object.Label,
                        remaining.source_freecad_object.Label,
                        relative_angle,
                        remaining.spacing,
                        remaining.deflection,
                        remaining.simplification
                    )
                    
                    # Skip if already submitted or cached
                    if cache_key in self._precomputed_keys:
                        continue
                    self._precomputed_keys.add(cache_key)
                    
                    with Shape.nfp_cache_lock:
                        if cache_key in Shape.nfp_cache:
                            continue
                    
                    # Fire-and-forget: compute in background, result goes to cache.
                    # Dispatch to GPU or CPU path to match the engine configuration.
                    nfp_fn = (
                        self.engine._calculate_and_cache_nfp_gpu
                        if self.engine.use_gpu
                        else self.engine._calculate_and_cache_nfp
                    )
                    self._precompute_pool.submit(
                        nfp_fn,
                        placed.shape, 0.0, remaining, relative_angle, cache_key
                    )