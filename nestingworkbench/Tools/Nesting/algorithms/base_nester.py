
import math
import copy
import random
from shapely.geometry import Polygon
from shapely.affinity import translate, rotate
from shapely.ops import unary_union
from PySide import QtGui
import FreeCAD
from ....datatypes.sheet import Sheet
from ....datatypes.placed_part import PlacedPart

class BaseNester(object):
    """
    Base class for nesting algorithms. 
    It provides a common greedy loop and utility methods for placement attempts.
    """
    def __init__(self, width, height, rotation_steps=1, **kwargs):
        self._bin_width = width
        self._bin_height = height
        self.rotation_steps = max(1, rotation_steps)
        self.max_spawn_count = kwargs.get("max_spawn_count", 100)
        self.anneal_steps = kwargs.get("anneal_steps", 25)
        self.step_size = kwargs.get("step_size", 5.0)
        self.anneal_rotate_enabled = kwargs.get("anneal_rotate_enabled", True)
        self.anneal_translate_enabled = kwargs.get("anneal_translate_enabled", True)
        self.anneal_random_shake_direction = kwargs.get("anneal_random_shake_direction", False)
        self.stability_tolerance = kwargs.get("stability_tolerance", 0.0001)
        self.verbose = kwargs.get("verbose", False)

        self.parts_to_place = []
        self.sheets = []
        self.update_callback = None
        self.progress_callback = None
        self.cancel_callback = kwargs.get("cancel_callback", None)
        
        self._bin_polygon = Polygon([(0, 0), (width, 0), (width, height), (0, height)])
        self._bin_boundary = self._bin_polygon.exterior

    def log(self, message):
        FreeCAD.Console.PrintMessage(f"NESTING: {message}\n")

    def nest(self, parts):
        """
        Main greedy nesting loop.
        """
        self.parts_to_place = list(parts)
        self.sheets = []
        
        # Sort biggest first
        self.parts_to_place.sort(key=lambda p: p.area, reverse=True)
        
        unplaced_parts = []
        total_count = len(self.parts_to_place)

        for i, part in enumerate(self.parts_to_place):
            if self.cancel_callback and self.cancel_callback():
                self.log("Cancelled by user.")
                break

            if self.progress_callback:
                self.progress_callback(i + 1, total_count, f"Placing {part.id}...")

            placed = False
            # 1. Try existing sheets
            for sheet in self.sheets:
                placed_shape = self._try_place_part_on_sheet(part, sheet)
                if placed_shape:
                    # Final placement on sheet origin
                    sheet_origin = sheet.get_origin()
                    placed_shape.placement = placed_shape.get_final_placement(sheet_origin)
                    sheet.add_part(PlacedPart(placed_shape))
                    
                    if self.update_callback:
                        self.update_callback(placed_shape, sheet)
                    
                    placed = True
                    break
            
            # 2. Try new sheet
            if not placed:
                new_sheet = Sheet(len(self.sheets), self._bin_width, self._bin_height)
                placed_shape = self._try_place_part_on_sheet(part, new_sheet)
                if placed_shape:
                    sheet_origin = new_sheet.get_origin()
                    placed_shape.placement = placed_shape.get_final_placement(sheet_origin)
                    new_sheet.add_part(PlacedPart(placed_shape))
                    self.sheets.append(new_sheet)
                    
                    if self.update_callback:
                        self.update_callback(placed_shape, new_sheet)
                    
                    placed = True
                else:
                    unplaced_parts.append(part)

            # Keep UI alive
            QtGui.QApplication.processEvents()

        return self.sheets, unplaced_parts

    def _try_place_part_on_sheet(self, shape, sheet):
        """Must be implemented by subclasses."""
        raise NotImplementedError

    def _evaluate_placement(self, shape, direction):
        """
        Evaluates a placement based on the centroid's position in gravity direction.
        Higher score = further along the direction vector.
        Uses the shape's centroid (part origin) as requested.
        Includes a small tie-breaker to favor the sheet origin (packing to the side).
        """
        center = shape.centroid
        if not center:
            return -float('inf')
            
        # 1. Primary score: distance along gravity direction
        primary_score = center.x * direction[0] + center.y * direction[1]
        
        # 2. Tie-breaker: small penalty for distance from origin
        # (center.x + center.y) effectively pushes to the bottom-left corner
        # if gravity is downward.
        tie_breaker = -(abs(center.x) + abs(center.y)) * 0.001
        
        return primary_score + tie_breaker

    def _anneal_part(self, part, sheet, direction, rotate_enabled=True, translate_enabled=True):
        """
        Opportunistic random walk.
        Shakes the part until a strictly better valid spot is found, then returns immediately.
        Returns True if a better spot was found, False otherwise.
        """
        if self.anneal_steps == 0 or (not rotate_enabled and not translate_enabled):
            return False

        initial_x, initial_y, _, _ = part.bounding_box()
        initial_angle = part.angle
        
        base_perp_dir = (-direction[1], direction[0])
        initial_side = random.choice([1, -1])

        # the baseline to beat
        starting_score = self._evaluate_placement(part, direction)
        best_score = starting_score
        best_state = (initial_x, initial_y, initial_angle)

        current_state = best_state
        
        # Minimum improvement required to be considered an "advantage" 
        # Prevents infinite loops due to floating point noise.
        EPSILON = self.stability_tolerance

        # LOGGING
        self.log(f"--- Annealing Cycle Start for {part.id} ---")
        self.log(f"  Pos Jumps: {self.anneal_steps}, Rotations per jump: {part.rotation_steps}")

        for i in range(self.anneal_steps):
            if self.cancel_callback and self.cancel_callback():
                self.log("Annealing cancelled.")
                break

            # PROGRESSIVE AMPLITUDE (Inverse Annealing / Expanding Radius)
            # Starts with tiny local wiggles (progress ~ 0)
            # Ends with wide global jumps (progress ~ 1.0)
            progress = (i + 1) / self.anneal_steps
            amplitude = self.step_size * progress * 10.0 
            
            # --- 1. SHAKE (Pick a new candidate position) ---
            part.move_to(current_state[0], current_state[1])
            part.set_rotation(current_state[2])

            if translate_enabled:
                if self.anneal_random_shake_direction:
                    rand_angle = random.uniform(0, 2 * math.pi)
                    move_dir = (math.cos(rand_angle), math.sin(rand_angle))
                else:
                    side = initial_side if i % 2 == 0 else -initial_side
                    move_dir = (base_perp_dir[0] * side, base_perp_dir[1] * side)
                
                part.move(move_dir[0] * amplitude, move_dir[1] * amplitude)

            cand_x, cand_y, _, _ = part.bounding_box()

            # --- 2. ROTATION SEARCH (Try strict orientations) ---
            pos_best_score = -float('inf')
            pos_best_angle = None
            
            rot_steps_to_try = part.rotation_steps if (rotate_enabled and part.rotation_steps > 1) else 1
            
            for r in range(rot_steps_to_try):
                target_angle = r * (360.0 / part.rotation_steps) if rot_steps_to_try > 1 else part.angle
                part.set_rotation(target_angle)
                
                if sheet.is_placement_valid(part, part_to_ignore=part):
                    score = self._evaluate_placement(part, direction)
                    if score > pos_best_score:
                        pos_best_score = score
                        pos_best_angle = target_angle
                        
                    # OPPORTUNISTIC EARLY EXIT: 
                    # Requires strictly better score + EPSILON breakthrough
                    if score > starting_score + EPSILON:
                        self.log(f"  Advantage found at PosStep {i:2d} (Amp={amplitude:.1f}mm), Rot {r:2d}: Score {score:10.6f} > {starting_score:10.6f}. EXITING EARLY.")
                        best_state = (cand_x, cand_y, target_angle)
                        part.move_to(best_state[0], best_state[1])
                        part.set_rotation(best_state[2])
                        return True

            # --- 3. EVALUATE JUMP (Internal walk progress) ---
            if pos_best_angle is not None:
                current_state = (cand_x, cand_y, pos_best_angle)
                part.set_rotation(pos_best_angle) 
                
                if pos_best_score > best_score:
                    best_score = pos_best_score
                    best_state = current_state
                
                self.log(f"  PosStep {i:2d}: Pos=({cand_x:6.1f}, {cand_y:6.1f}), BestAngle={pos_best_angle:5.1f}, Score={pos_best_score:10.6f} (Wiggle)")
            else:
                part.move_to(current_state[0], current_state[1])
                part.set_rotation(current_state[2])
                if self.verbose:
                    self.log(f"  PosStep {i:2d}: Invalid")
        
        # If we reached here, we finished all steps without an "advantage" jump.
        # Check if we at least found a marginally better spot than the start.
        if best_score > starting_score + EPSILON:
            self.log(f"Annealing finished with improvement. Best Score: {best_score:10.6f}")
            part.move_to(best_state[0], best_state[1])
            part.set_rotation(best_state[2])
            return True
        else:
            self.log(f"Annealing finished (no improvement). Baseline: {starting_score:10.6f}")
            part.move_to(initial_x, initial_y)
            part.set_rotation(initial_angle)
            return False

