"""
LayoutManager - Handles creation, cloning, and management of Layout objects.

This class is responsible for:
- Creating new layouts with master shapes and part instances
- Cloning layouts for GA population members
- Deleting layouts and all their child objects
- Calculating layout efficiency

Separates layout management from the nesting algorithm for cleaner architecture.
"""

import FreeCAD
import copy
from .shape_preparer import ShapePreparer
from ...datatypes.shape import Shape
from ...freecad_helpers import recursive_delete

class Layout:
    """
    Represents a single layout attempt (population member in GA).
    Contains references to the FreeCAD objects and the parts list.
    
    Attributes:
        genes: List of (part_id, angle) tuples representing the ordering and rotation
               of parts. Can be used to recreate the exact same layout.
    """
    def __init__(self, layout_group, parts_group, parts, master_shapes_group=None):
        self.layout_group = layout_group  # The Layout_xxx group object
        self.parts_group = parts_group    # The PartsToPlace group
        self.parts = parts                # List of Shape objects for nesting
        self.master_shapes_group = master_shapes_group
        self.sheets = []                  # Filled after nesting
        self.fitness = float('inf')
        self.efficiency = 0.0
        self.genes = []                   # (part_id, angle) tuples - the "DNA" of this layout
    
    @property
    def name(self):
        return self.layout_group.Label if self.layout_group else "unknown"

class LayoutManager:
    """
    Manages layout creation, cloning, and deletion.
    Acts as a factory for Layout objects used in nesting.
    """
    
    def __init__(self, doc, processed_shape_cache=None):
        self.doc = doc
        self.processed_shape_cache = processed_shape_cache or {}
        self._layout_counter = 0
    
    def create_layout(self, name, master_shapes_map, quantities, ui_params, 
                      chromosome_ordering=None) -> Layout:
        """
        Creates a new layout with master shapes and part instances.
        
        Args:
            name: Name for the layout (e.g., "Layout_GA_1")
            master_shapes_map: Dict mapping labels to FreeCAD shape objects
            quantities: Dict mapping labels to (quantity, rotation_steps)
            ui_params: UI parameters dict
            chromosome_ordering: Optional list of (part_id, angle) tuples for ordering
            
        Returns:
            Layout object containing the layout group and prepared parts
        """
        # Create layout group
        layout_group = self.doc.addObject("App::DocumentObjectGroup", name)
        layout_group.Label = name
        if hasattr(layout_group, "ViewObject"):
            layout_group.ViewObject.Visibility = True
        
        # Create parts bin
        parts_group = self.doc.addObject("App::DocumentObjectGroup", "PartsToPlace")
        layout_group.addObject(parts_group)
        
        # Create shape preparer for this layout
        preparer = ShapePreparer(self.doc, self.processed_shape_cache)
        
        # Prepare parts (creates masters and instances)
        parts = preparer.prepare_parts(
            ui_params, quantities, master_shapes_map, 
            layout_group, parts_group
        )
        
        # Get master shapes group
        master_shapes_group = None
        for child in layout_group.Group:
            if child.Label == "MasterShapes":
                master_shapes_group = child
                break
        
        # Apply chromosome ordering if provided
        if chromosome_ordering and parts:
            parts = self._apply_ordering(parts, chromosome_ordering)
        
        self._layout_counter += 1
        
        return Layout(layout_group, parts_group, parts, master_shapes_group)
    
    def _apply_ordering(self, parts, chromosome_ordering):
        """
        Reorders and rotates parts according to a chromosome.
        
        Args:
            parts: List of Shape objects
            chromosome_ordering: List of (part_id, angle) tuples
            
        Returns:
            Reordered list of Shape objects with rotations applied
        """
        if not chromosome_ordering:
            return parts
        
        # Build a map of part id -> part
        parts_map = {p.id: p for p in parts}
        
        ordered_parts = []
        for part_id, angle in chromosome_ordering:
            if part_id in parts_map:
                part = parts_map[part_id]
                if angle is not None:
                    part.set_rotation(angle)
                ordered_parts.append(part)
        
        return ordered_parts
    
    def delete_layout(self, layout, verbose=False):
        """
        Removes a layout group and ALL its children from the document.
        Must recursively delete children first since FreeCAD doesn't do this automatically.
        
        Args:
            layout: Layout object to delete
            verbose: If True, log deletion
        """
        if not layout:
            return
            
        # Check if already deleted
        if hasattr(layout, '_deleted') and layout._deleted:
            return
        
        # Get the group object before we mark it deleted
        group_obj = None
        try:
            if layout.layout_group:
                group_obj = layout.layout_group
        except Exception:
            pass
        
        layout_label = layout.name if hasattr(layout, 'name') else "unknown"
        
        # Mark as deleted immediately to prevent re-entry
        layout._deleted = True
        layout.layout_group = None
        layout.sheets = []
        layout.parts = []
        
        # Recursively delete the group and all children
        if group_obj:
            recursive_delete(self.doc, group_obj)
            if verbose:
                FreeCAD.Console.PrintMessage(f"  Deleted: {layout_label}\n")

    

    
    def calculate_efficiency(self, layout, sheet_width, sheet_height) -> tuple:
        """
        Calculates the packing efficiency of a layout.
        
        Args:
            layout: Layout object with sheets populated
            sheet_width: Width of each sheet
            sheet_height: Height of each sheet
            
        Returns:
            (fitness, efficiency_percent) tuple
        """
        if not layout.sheets:
            return float('inf'), 0.0
        
        # Calculate total parts area
        total_parts_area = 0
        for sheet in layout.sheets:
            for part in sheet.parts:
                if hasattr(part, 'shape') and part.shape:
                    total_parts_area += part.shape.area
        
        # Calculate total sheet area
        total_sheet_area = len(layout.sheets) * sheet_width * sheet_height
        
        # Efficiency percentage
        efficiency = (total_parts_area / total_sheet_area) * 100 if total_sheet_area > 0 else 0
        
        # Fitness: lower is better
        # Prioritize fewer sheets, then tighter bounding box
        fitness = len(layout.sheets) * sheet_width * sheet_height
        
        # Add bounding box of last sheet
        last_sheet = layout.sheets[-1]
        if last_sheet.parts:
            min_x, min_y = float('inf'), float('inf')
            max_x, max_y = float('-inf'), float('-inf')
            found_valid = False
            
            for p in last_sheet.parts:
                try:
                    bx, by, bw, bh = p.shape.bounding_box()
                    min_x = min(min_x, bx)
                    min_y = min(min_y, by)
                    max_x = max(max_x, bx + bw)
                    max_y = max(max_y, by + bh)
                    found_valid = True
                except Exception as e:
                    part_id = getattr(p.shape, 'id', 'unknown') if hasattr(p, 'shape') else 'unknown'
                    FreeCAD.Console.PrintWarning(f"[LayoutManager] Bounding box failed for part '{part_id}': {e}\n")
            
            if found_valid:
                fitness += (max_x - min_x) * (max_y - min_y)
        
        layout.fitness = fitness
        layout.efficiency = efficiency

        return fitness, efficiency
    
    def create_ga_population(self, master_shapes_map, quantities, ui_params, 
                             population_size, rotation_steps=1, verbose=False) -> list:
        """
        Creates a population of layouts for genetic algorithm.
        
        Args:
            master_shapes_map: Dict mapping labels to FreeCAD shape objects
            quantities: Dict mapping labels to (quantity, rotation_steps)
            ui_params: UI parameters dict
            population_size: Number of layouts to create
            rotation_steps: Number of rotation steps for random rotations
            
        Returns:
            List of Layout objects
        """
        import random
        
        population = []
        
        for i in range(population_size):
            name = f"Layout_GA_{i+1}"
            
            # Create the layout
            layout = self.create_layout(name, master_shapes_map, quantities, ui_params)
            
            if layout.parts and i > 0:  # First layout keeps original ordering
                # Shuffle the parts order
                random.shuffle(layout.parts)
                
                # Apply random rotations
                if rotation_steps > 1:
                    for part in layout.parts:
                        angle = random.randrange(rotation_steps) * (360.0 / rotation_steps)
                        part.set_rotation(angle)
            
            population.append(layout)
            if verbose:
                FreeCAD.Console.PrintMessage(f"Created layout {name} with {len(layout.parts)} parts\n")
        
        return population
    
