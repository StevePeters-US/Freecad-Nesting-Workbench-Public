
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

    def _calculate_contact_score(self, shape, sheet):
        """
        Calculates a score based on how much the shape's boundary 
        touches other shapes or the sheet border.
        Higher score = better (tighter fit).
        """
        if not shape.polygon or shape.polygon.is_empty:
            return 0.0
            
        # Small buffer to detect "almost touching"
        eps = 0.5 
        buffered = shape.polygon.buffer(eps)
        
        score = 0.0
        
        # 1. Contact with sheet borders
        try:
            border_overlap = buffered.intersection(self._bin_boundary)
            if not border_overlap.is_empty:
                # Intersection with exterior line is a (Multi)LineString
                score += border_overlap.length
        except Exception:
            pass
            
        # 2. Contact with other parts
        neighbors = [p.shape.polygon for p in sheet.parts if p.shape and p.shape.polygon]
        if neighbors:
            try:
                # union neighbors for faster intersection check
                neighbors_union = unary_union(neighbors)
                neighbor_overlap = buffered.intersection(neighbors_union)
                if not neighbor_overlap.is_empty:
                    # Intersection of buffered poly with neighbor poly is a strip poly
                    # Its length (perimeter) is proportional to contact length
                    score += neighbor_overlap.length
            except Exception:
                pass
                
        return score

    def _anneal_part(self, part, sheet, direction, rotate_enabled=True, translate_enabled=True):
        """
        Narrowing random walk to find a better valid spot.
        Start with large random jumps and progressively narrow to fine adjustments.
        """
        if self.anneal_steps == 0 or (not rotate_enabled and not translate_enabled):
            return

        initial_x, initial_y, _, _ = part.bounding_box()
        initial_angle = part.angle
        
        base_perp_dir = (-direction[1], direction[0])
        initial_side = random.choice([1, -1])

        # Track the best configuration found so far DURING this annealing call
        best_score = self._calculate_contact_score(part, sheet)
        best_state = (initial_x, initial_y, initial_angle)

        for i in range(self.anneal_steps):
            if self.cancel_callback and self.cancel_callback():
                break

            progress = i / self.anneal_steps
            
            # Reset to current best before taking a new random jump
            part.move_to(best_state[0], best_state[1])
            part.set_rotation(best_state[2])

            # 1. Rotation (Narrowing Random Walk)
            if rotate_enabled and part.rotation_steps > 1:
                # Decrease max jump radius from 50% circle to ~1 step
                max_jump = max(1, int((part.rotation_steps // 2) * (1.0 - progress)))
                offset = random.randint(-max_jump, max_jump)
                
                current_step = round(best_state[2] / (360.0 / part.rotation_steps))
                new_step = (current_step + offset) % part.rotation_steps
                new_angle = new_step * (360.0 / part.rotation_steps)
                part.set_rotation(new_angle)

            # 2. Translation (Similarly narrows its shake radius)
            if translate_enabled:
                amplitude = self.step_size * (1.0 - progress) * 2.0  # Optional: Scale by progress
                # Re-calculate side logic or use randomness
                if self.anneal_random_shake_direction:
                    rand_angle = random.uniform(0, 2 * math.pi)
                    move_dir = (math.cos(rand_angle), math.sin(rand_angle))
                else:
                    side = initial_side if i % 2 == 0 else -initial_side
                    move_dir = (base_perp_dir[0] * side, base_perp_dir[1] * side)
                
                part.move(move_dir[0] * amplitude, move_dir[1] * amplitude)

            # Check if this new test configuration is valid
            if sheet.is_placement_valid(part, part_to_ignore=part):
                score = self._calculate_contact_score(part, sheet)
                # If it's the best score we've seen, update our current 'best' state
                if score > best_score:
                    best_score = score
                    bx, by, _, _ = part.bounding_box()
                    best_state = (bx, by, part.angle)
        
        # Apply the absolute best state found during the walk
        part.move_to(best_state[0], best_state[1])
        part.set_rotation(best_state[2])

