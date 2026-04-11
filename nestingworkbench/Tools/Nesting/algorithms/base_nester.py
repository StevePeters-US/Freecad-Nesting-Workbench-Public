
import math
import copy
import random
from shapely.geometry import Polygon
from shapely.affinity import translate, rotate
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
        self.anneal_steps = kwargs.get("anneal_steps", 100)
        self.step_size = kwargs.get("step_size", 5.0)
        self.anneal_rotate_enabled = kwargs.get("anneal_rotate_enabled", True)
        self.anneal_translate_enabled = kwargs.get("anneal_translate_enabled", True)
        self.anneal_random_shake_direction = kwargs.get("anneal_random_shake_direction", False)

        self.parts_to_place = []
        self.sheets = []
        self.update_callback = None
        self.progress_callback = None
        
        self._bin_polygon = Polygon([(0, 0), (width, 0), (width, height), (0, height)])

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

    def _anneal_part(self, part, sheet, direction, rotate_enabled=True, translate_enabled=True):
        """
        Local search to find a valid spot when stuck.
        """
        if self.anneal_steps == 0 or (not rotate_enabled and not translate_enabled):
            return

        initial_x, initial_y, _, _ = part.bounding_box()
        initial_angle = part.angle
        
        base_perp_dir = (-direction[1], direction[0])
        initial_side = random.choice([1, -1])

        for i in range(self.anneal_steps):
            amplitude = self.step_size * (i // 2 + 1)
            side = initial_side if i % 2 == 0 else -initial_side

            # Reset
            part.move_to(initial_x, initial_y)
            part.set_rotation(initial_angle)

            if rotate_enabled and part.rotation_steps > 1:
                step_deg = (360.0 / part.rotation_steps) * (i // 2 + 1)
                new_angle = (initial_angle + step_deg * side) % 360.0
                part.set_rotation(new_angle)

            if translate_enabled:
                if self.anneal_random_shake_direction:
                    rand_angle = random.uniform(0, 2 * math.pi)
                    move_dir = (math.cos(rand_angle), math.sin(rand_angle))
                else:
                    move_dir = (base_perp_dir[0] * side, base_perp_dir[1] * side)
                
                part.move(move_dir[0] * amplitude, move_dir[1] * amplitude)

            if sheet.is_placement_valid(part, part_to_ignore=part):
                return
        
        # Revert if no luck
        part.move_to(initial_x, initial_y)
        part.set_rotation(initial_angle)

