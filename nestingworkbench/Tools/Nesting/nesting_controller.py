
import FreeCAD
import FreeCADGui
import Part
import os
import time
import math
from PySide import QtGui
from ...datatypes.shape import Shape
from .shape_preparer import ShapePreparer
from .layout_manager import LayoutManager, Layout
from .ga_coordinator import GACoordinator
from ...freecad_helpers import recursive_delete
from ...constants import *

try:
    from .nesting_logic import nest, NestingDependencyError
except ImportError:
    pass

class NestingJob:
    """
    Manages a single nesting session using the Sandbox Pattern.
    - Creates a temporary environment (Layout_temp).
    - Runs the nesting algorithm.
    - Commits results to a permanent target layout or discards them on cancel.
    """
    def __init__(self, doc, target_layout, ui_params, preparer):
        self.doc = doc
        self.target_layout = target_layout
        self.params = ui_params
        self.preparer = preparer
        
        self.temp_layout = None
        self.parts_group = None # The "PartsToPlace" bin
        self.sheets = []
        
        self._owned_object_names: set[str] = set()
        self._init_sandbox()

    @classmethod
    def from_ga_result(cls, doc, target_layout, params, preparer, layout_group, parts_group, sheets):
        """Creates a NestingJob from a completed GA layout, bypassing sandbox creation."""
        job = cls.__new__(cls)
        job.doc = doc
        job.target_layout = target_layout
        job.params = params
        job.preparer = preparer
        job.temp_layout = layout_group
        job.parts_group = parts_group
        job.sheets = sheets
        
        job._owned_object_names = set()
        if layout_group: job._owned_object_names.add(layout_group.Name)
        if parts_group: job._owned_object_names.add(parts_group.Name)
        
        return job

    def _init_sandbox(self):
        """Creates the temporary layout and parts bin."""
        self.temp_layout = self.doc.addObject("App::DocumentObjectGroup", "Layout_temp")
        self.parts_group = self.doc.addObject("App::DocumentObjectGroup", "PartsToPlace")
        
        self._owned_object_names.add(self.temp_layout.Name)
        self._owned_object_names.add(self.parts_group.Name)
        
        self.temp_layout.addObject(self.parts_group)
        
        if hasattr(self.temp_layout, "ViewObject"):
            self.temp_layout.ViewObject.Visibility = True
            


    def run(self, quantities, master_map, rotation_params, algo_kwargs, is_simulating=False):
        """Executes the nesting logic: Prepare -> Nest -> Draw."""
        
        # 1. Prepare Shapes
        parts_to_nest = self.preparer.prepare_parts(
            self.params, quantities, master_map, self.temp_layout, self.parts_group
        )
        
        if not parts_to_nest:
            raise ValueError("No valid parts to nest.")

        # 1.5 Persist Metadata (Quantity, Rotations) to Master Containers
        self._persist_metadata(quantities, rotation_params)

        # 2. Run Algorithm
        # Ensure verbose is in algo_kwargs if present in params
        if 'verbose_logging' in self.params:
            algo_kwargs['verbose'] = self.params['verbose_logging']

        self.sheets, unplaced, steps, elapsed = nest(
            parts_to_nest, 
            self.params['sheet_width'], 
            self.params['sheet_height'],
            self.params['rotation_steps'], 
            is_simulating, 
            **algo_kwargs
        )
        
        # Warn about unplaced parts
        if unplaced:
            unplaced_ids = [p.id for p in unplaced]
            FreeCAD.Console.PrintWarning(f"WARNING: {len(unplaced)} part(s) could not be placed: {unplaced_ids}\n")
        
        if not is_simulating:
            self._apply_placement(self.sheets, parts_to_nest)
            
        # 3. Draw Results (into Temp Layout)
        # Note: sheet.draw now handles unlinking from PartsToPlace!
        verbose = self.params.get('verbose_logging', False)
        for sheet in self.sheets:
            sheet.draw(self.doc, self.params, self.temp_layout, parts_to_place_group=self.parts_group, verbose=verbose)
            
        return len(self.sheets), sum(len(s) for s in self.sheets)

    def _persist_metadata(self, quantities, rotation_params):
        master_group = self.temp_layout.getObject("MasterShapes")
        if not master_group:
            FreeCAD.Console.PrintWarning("[NestingJob] MasterShapes group not found in sandbox, cannot persist metadata.\n")
            return
        
        for container in master_group.Group:
             if not hasattr(container, "Group"): continue
             
             # Find inner shape label
             shape = next((c for c in container.Group if c.Label.startswith("master_shape_")), None)
             if shape:
                 original_label = shape.Label.replace("master_shape_", "")
                 
                 # Save Quantity
                 # quantities dict is {label: (qty, rotation_steps)}
                 qty_tuple = quantities.get(original_label) 
                 if qty_tuple:
                     qty = qty_tuple[0]
                     if not hasattr(container, "Quantity"):
                         container.addProperty("App::PropertyInteger", "Quantity", "Nesting", "Part Quantity")
                     container.Quantity = qty

                 # Save Rotation Overrides
                 if original_label in rotation_params:
                     # rotation_params is {label: (val, override_bool)}
                     r_val, r_override = rotation_params[original_label]
                     
                     if not hasattr(container, "PartRotationSteps"):
                          container.addProperty("App::PropertyInteger", "PartRotationSteps", "Nesting", "Rotation steps")
                     if not hasattr(container, "PartRotationOverride"):
                          container.addProperty("App::PropertyBool", "PartRotationOverride", "Nesting", "Override global rotation")
                     
                     container.PartRotationSteps = int(r_val)
                     container.PartRotationOverride = bool(r_override)

    def commit(self):
        """Promotes the temporary results to the target layout."""
        
        # 1. Clean Target of old results (Sheets)
        # We do NOT remove MasterShapes unless we have new ones to replace them?
        # Current logic: If we re-ran, we overwrite sheets.
        to_remove = []
        for child in self.target_layout.Group:
            if child.Label.startswith("Sheet_"):
                to_remove.append(child)
        
        for child in to_remove:
            recursive_delete(self.doc, child)
            
        # 2. Check for new MasterShapes in Temp
        temp_masters = next((c for c in self.temp_layout.Group if c.Label.startswith("MasterShapes")), None)
        
        if temp_masters and len(temp_masters.Group) > 0:
            # We have new masters, replace old ones in Target
            old_masters = next((c for c in self.target_layout.Group if c.Label.startswith("MasterShapes")), None)
            if old_masters:
                recursive_delete(self.doc, old_masters)
            
            # Sanitize labels before move
            temp_masters.Label = "MasterShapes"
            for m in temp_masters.Group:
                if m.Label.startswith("temp_master_"):
                    m.Label = m.Label.replace("temp_master_", "master_")
            
            self.temp_layout.removeObject(temp_masters)
            self.target_layout.addObject(temp_masters)
            
        else:
            # No new masters, if temp has empty master group, delete it
            if temp_masters:
                recursive_delete(self.doc, temp_masters)

        # 3. Move Sheets from Temp to Target
        # IMPORTANT: explicitly removeObject from temp first, because FreeCAD's addObject
        # does NOT automatically remove from the old group. If sheets remain in
        # temp_layout.Group when cleanup() calls recursive_delete(temp_layout), it will
        # walk into the sheets' children and delete Shapes_ groups and nested_xxx containers.
        sheets_to_move = [c for c in self.temp_layout.Group if c.Label.startswith("Sheet_")]
        for sheet in sheets_to_move:
            self.temp_layout.removeObject(sheet)
            self.target_layout.addObject(sheet)

        # 4. Clean up Temp (Sandbox)
        # PartsToPlace should be empty of placed parts due to unlinking in Sheet.draw
        # Any unplaced parts remain there and will be deleted.
        self.cleanup()
        
        # 5. Apply Properties to Target
        self._apply_properties(self.target_layout)
        
        return self.target_layout

    def cleanup(self):
        """Destroys the sandbox."""
        for name in list(self._owned_object_names):
            obj = self.doc.getObject(name)
            if obj:
                recursive_delete(self.doc, obj)
        self._owned_object_names.clear()
        
        self.temp_layout = None
        self.parts_group = None



    def _apply_placement(self, sheets, parts_to_nest):
        original_parts_map = {part.id: part for part in parts_to_nest}
        for sheet in sheets:
            for i, placed_part in enumerate(sheet.parts):
                 original_part = original_parts_map[placed_part.shape.id]
                 # Calculate placement relative to sheet origin
                 # Calculate placement relative to sheet origin
                 sheet_origin = sheet.get_origin()
                 original_part.placement = placed_part.shape.get_final_placement(sheet_origin)
                 sheet.parts[i].shape = original_part

    def _apply_properties(self, layout_obj):
        p = self.params
        self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_WIDTH, p['sheet_width'])
        self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_HEIGHT, p['sheet_height'])
        self._set_prop(layout_obj, PROP_LENGTH, PROP_PART_SPACING, p['spacing'])
        self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_THICKNESS, p['sheet_thickness'])
        self._set_prop(layout_obj, PROP_FLOAT, PROP_DEFLECTION_ANGLE, p.get('deflection_angle', 30))  # Save angle in degrees
        self._set_prop(layout_obj, PROP_FLOAT, PROP_SIMPLIFICATION, p.get('simplification', 1.0))
        self._set_prop(layout_obj, PROP_FILE, PROP_FONT_FILE, p['font_path'])
        self._set_prop(layout_obj, PROP_BOOL, PROP_SHOW_BOUNDS, p['show_bounds'])
        self._set_prop(layout_obj, PROP_BOOL, PROP_ADD_LABELS, p['add_labels'])
        self._set_prop(layout_obj, PROP_LENGTH, PROP_LABEL_HEIGHT, p['label_height'])
        self._set_prop(layout_obj, PROP_FLOAT, PROP_LABEL_SIZE, p['label_size'])
        self._set_prop(layout_obj, PROP_INTEGER, PROP_GLOBAL_ROTATION_STEPS, p['rotation_steps'])
        self._set_prop(layout_obj, PROP_INTEGER, PROP_GENERATIONS, p.get('generations', 1))
        self._set_prop(layout_obj, PROP_INTEGER, PROP_POPULATION_SIZE, p.get('population_size', 1))
        self._set_prop(layout_obj, PROP_BOOL, PROP_USE_GPU, p.get('use_gpu', False))
        
        # Save Nesting Direction as a vector/tuple if possible, or just the dial value
        # For simplicity and transparency in the UI, we'll save the dial value (degrees)
        dial_val = p.get('nesting_direction', 0)
        self._set_prop(layout_obj, PROP_INTEGER, PROP_NESTING_DIRECTION, dial_val)

    def _set_prop(self, obj, type_str, name, val):
        if not hasattr(obj, name):
            obj.addProperty(type_str, name, "Layout", "")
        setattr(obj, name, val)


class NestingController:
    """
    Main controller for the Nesting Workbench.
    Handles UI interaction, Job creation, and Layout management.
    """
    def __init__(self, ui_panel):
        self.ui = ui_panel
        self.doc = FreeCAD.ActiveDocument
        self.current_job = None
        self.shape_preparer = ShapePreparer(self.doc, {})
        self.is_running = False
        self.cancel_requested = False
        
        # Initialize default fonts
        font_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'fonts'))
        default_font = os.path.join(font_dir, 'PoiretOne-Regular.ttf')
        self.ui.selected_font_path = default_font
        if hasattr(self.ui, 'font_label'):
            self.ui.font_label.setText(os.path.basename(default_font))

    def execute_nesting(self):
        FreeCAD.Console.PrintMessage("\n--- NESTING START ---\n")
        
        if self.current_job:
            self.current_job.cleanup()
            self.current_job = None

        # Clear stale caches from previous nesting runs
        Shape.clear_caches()

        # 1. Ensure Target Layout Exists (Create default if needed)
        target_layout = self._ensure_target_layout()
        if not target_layout:
             return # Standard error handled in helper
             
        # Hide target during operation
        if hasattr(target_layout, "ViewObject"):
            target_layout.ViewObject.Visibility = False

        # 2. Collect Parameters
        ui_params = self._collect_ui_params()
        ui_params, quantities, master_map, rotation_params = self._collect_job_parameters(ui_params)
        
        algo_kwargs = self._prepare_algo_kwargs(ui_params)
        is_simulating = self.ui.simulate_nesting_checkbox.isChecked()
        verbose = self.ui.verbose_logging_checkbox.isChecked()
        algo_kwargs['verbose'] = verbose
        
        # VERIFICATION LOGS for the user
        rot_steps = ui_params.get('rotation_steps', 1)
        ann_steps = algo_kwargs.get('anneal_steps', 25) if ui_params.get('algorithm') == 'Physics' else 0
        FreeCAD.Console.PrintMessage(f"Algorithm Selected: {ui_params.get('algorithm', 'Unknown')}\n")
        FreeCAD.Console.PrintMessage(f"  -> UI Rotation Steps Slider: {rot_steps}\n")
        FreeCAD.Console.PrintMessage(f"  -> UI Anneal Steps Input: {ann_steps}\n")
        
        algo_kwargs['cancel_callback'] = self._check_cancel
        
        # Persist verbose setting
        prefs = FreeCAD.ParamGet(PREFS_PATH)
        prefs.SetBool("VerboseLogging", verbose)
        
        # 3. Execute nesting using unified GA path
        # (population=1, generations=1 is equivalent to standard nesting)
        
        # Define progress callback
        def progress_cb(current, total, message=None):
            try:
                self.ui.update_progress(current, total, message)
            except RuntimeError: pass
            
        self.ui.reset_progress()
        algo_kwargs['progress_callback'] = progress_cb
        
        try:
            self.is_running = True
            self.cancel_requested = False
            self.ui.nest_button.setEnabled(False)
            self.ui.cancel_button.setEnabled(True)
            self._execute_ga_nesting(target_layout, ui_params, quantities, master_map, 
                                     rotation_params, algo_kwargs, is_simulating)
        finally:
            self.is_running = False
            self.cancel_requested = False
            self.ui.nest_button.setEnabled(True)
            self.ui.cancel_button.setEnabled(False)
            # Ensure progress bar is reset on finish/error
            self.ui.reset_progress()
    
    def load_selection(self):
        FreeCAD.Console.PrintMessage("Loading selection via Controller...\n")
        selection = FreeCADGui.Selection.getSelection()
        self.ui.shape_table.setRowCount(0)

        if not selection:
            FreeCAD.Console.PrintMessage("  -> No selection found.\n")
            self.ui.status_label.setText("Warning: No shapes selected.")
            self.ui.nest_button.setEnabled(False)
            return

        # Check if a layout group is selected
        first_selected = selection[0]
        if first_selected.isDerivedFrom("App::DocumentObjectGroup") and first_selected.Label.startswith("Layout_"):
            FreeCAD.Console.PrintMessage(f"  -> Detected layout selection: {first_selected.Label}\n")
            self.load_layout(first_selected)
        else:
            FreeCAD.Console.PrintMessage(f"  -> Detected {len(selection)} shapes.\n")
            self.load_shapes(selection)

    def load_layout(self, layout_group):
        """Loads the parameters and shapes from a layout group."""
        self.ui.current_layout = layout_group
        self.ui.nest_button.setEnabled(True)
        self.ui.selected_shapes_to_process = []
        self.ui.hidden_originals = []

        # Read parameters directly from the layout group's properties
        if hasattr(layout_group, PROP_SHEET_WIDTH):
            self.ui.sheet_width_input.setValue(getattr(layout_group, PROP_SHEET_WIDTH))
        if hasattr(layout_group, PROP_SHEET_HEIGHT):
            self.ui.sheet_height_input.setValue(getattr(layout_group, PROP_SHEET_HEIGHT))
        if hasattr(layout_group, PROP_PART_SPACING):
            self.ui.part_spacing_input.setValue(getattr(layout_group, PROP_PART_SPACING))
        if hasattr(layout_group, PROP_SHEET_THICKNESS):
            self.ui.sheet_thickness_input.setValue(getattr(layout_group, PROP_SHEET_THICKNESS))
        
        # Load deflection angle (new format) or convert old deflection mm to angle
        if hasattr(layout_group, PROP_DEFLECTION_ANGLE):
            self.ui.deflection_input.setValue(getattr(layout_group, PROP_DEFLECTION_ANGLE))
        elif hasattr(layout_group, 'Deflection'):
            # Backward compatibility: convert old Deflection (mm) to angle
            deflection_angle = layout_group.Deflection * 200.0
            self.ui.deflection_input.setValue(deflection_angle)
            
        if hasattr(layout_group, PROP_SIMPLIFICATION):
            self.ui.simplification_input.setValue(getattr(layout_group, PROP_SIMPLIFICATION))
        if hasattr(layout_group, PROP_FONT_FILE):
            font_path = getattr(layout_group, PROP_FONT_FILE)
            if os.path.exists(font_path):
                self.ui.selected_font_path = font_path
                self.ui.font_label.setText(os.path.basename(font_path))
        if hasattr(layout_group, PROP_LABEL_SIZE):
            self.ui.label_size_input.setValue(getattr(layout_group, PROP_LABEL_SIZE))
        if hasattr(layout_group, PROP_GENERATIONS):
            self.ui.minkowski_generations_input.setValue(getattr(layout_group, PROP_GENERATIONS))
        if hasattr(layout_group, PROP_POPULATION_SIZE):
            self.ui.minkowski_population_size_input.setValue(getattr(layout_group, PROP_POPULATION_SIZE))
        if hasattr(layout_group, PROP_USE_GPU):
            self.ui.use_gpu_checkbox.setChecked(getattr(layout_group, PROP_USE_GPU))
        if hasattr(layout_group, PROP_NESTING_DIRECTION):
            self.ui.minkowski_direction_dial.setValue(getattr(layout_group, PROP_NESTING_DIRECTION))

        # Get the shapes from the layout
        master_shapes_group = None
        for child in layout_group.Group:
            if child.Label.startswith("MasterShapes"):
                master_shapes_group = child
                break
        
        if master_shapes_group:
            # The master shapes are now copies inside this group.
            # We need to find the actual ShapeObject inside each 'master_' container,
            # as that is what the processing logic expects.
            shapes_to_load = []
            quantities = {}
            rotation_overrides = {}
            rotation_steps_map = {}
            up_directions = {}
            fill_sheet_map = {}
            
            for master_container in master_shapes_group.Group:
                # Use a relaxed check for the container to ensure robust loading.
                if hasattr(master_container, "Group"):
                    # The object to load is the 'master_shape_...' object inside the container.
                    shape_obj = next((child for child in master_container.Group if child.Label.startswith("master_shape_")), None)
                    if shape_obj and hasattr(shape_obj, "Shape"):
                        shapes_to_load.append(shape_obj)
                        
                        # Recover properties from container
                        quantities[shape_obj.Label] = getattr(master_container, "Quantity", 1)
                        
                        if hasattr(master_container, "PartRotationOverride"):
                            rotation_overrides[shape_obj.Label] = master_container.PartRotationOverride
                        if hasattr(master_container, "PartRotationSteps"):
                            rotation_steps_map[shape_obj.Label] = master_container.PartRotationSteps
                        if hasattr(master_container, "UpDirection"):
                            up_directions[shape_obj.Label] = master_container.UpDirection
                        if hasattr(master_container, "FillSheet"):
                            fill_sheet_map[shape_obj.Label] = master_container.FillSheet
            
            self.load_shapes(
                shapes_to_load, 
                is_reloading_layout=True, 
                initial_quantities=quantities,
                initial_overrides=rotation_overrides,
                initial_rotation_steps=rotation_steps_map,
                initial_up_directions=up_directions,
                initial_fill_sheet=fill_sheet_map
            )
            
            # Load Global Rotation Steps if present
            if hasattr(layout_group, PROP_GLOBAL_ROTATION_STEPS):
                steps = getattr(layout_group, PROP_GLOBAL_ROTATION_STEPS)
                if steps > 0:
                    target_angle = 360.0 / steps
                    # Find closest angle in appropriate mapping
                    closest_idx = 0
                    min_diff = float('inf')
                    
                    # Logic depends on algorithm of the layout
                    is_physics = getattr(layout_group, "Algorithm", "") == "Physics"
                    if is_physics:
                        self.ui.algorithm_dropdown.setCurrentText("Physics")
                        phys_angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]
                        for i, angle in enumerate(phys_angles):
                            diff = abs(angle - target_angle)
                            if diff < min_diff:
                                min_diff = diff
                                closest_idx = i
                        self.ui.physics_rotation_steps_slider.setValue(closest_idx)
                    else:
                        self.ui.algorithm_dropdown.setCurrentText("Minkowski")
                        for i, angle in enumerate(self.ui.rotation_angles):
                            diff = abs(angle - target_angle)
                            if diff < min_diff:
                                min_diff = diff
                                closest_idx = i
                        self.ui.minkowski_rotation_steps_slider.setValue(closest_idx)
        else:
            FreeCAD.Console.PrintMessage(f"  WARNING: No MasterShapes group found!\n")
            self.ui.status_label.setText("Warning: Could not find 'MasterShapes' group in the selected layout.")

    def _extract_parts_from_selection(self, selection):
        """
        Extracts parts from Assembly containers only.
        Regular Part objects are used directly without extracting children.
        """
        parts = []
        
        def is_assembly(obj):
            """Check if object is an Assembly container (not a regular Part/Body)."""
            type_id = obj.TypeId if hasattr(obj, 'TypeId') else ''
            if 'Assembly' in type_id:
                return True
            if type_id == 'App::Part' and hasattr(obj, 'Group'):
                for child in obj.Group:
                    child_type = child.TypeId if hasattr(child, 'TypeId') else ''
                    if 'Link' in child_type or 'Assembly' in child_type:
                        return True
            return False
        
        def extract_from_assembly(obj):
            """Recursively extract nestable parts from an assembly."""
            if hasattr(obj, 'Group'):
                for child in obj.Group:
                    child_type = child.TypeId if hasattr(child, 'TypeId') else ''
                    if 'Constraint' in child_type or 'Origin' in child_type:
                        continue
                    if hasattr(child, 'LinkedObject') and child.LinkedObject:
                        linked = child.LinkedObject
                        if hasattr(linked, 'Shape') and linked.Shape and not linked.Shape.isNull():
                            parts.append(linked)
                    elif hasattr(child, 'Shape') and child.Shape and not child.Shape.isNull():
                        if is_assembly(child):
                            extract_from_assembly(child)
                        else:
                            parts.append(child)
        
        for obj in selection:
            if is_assembly(obj):
                extract_from_assembly(obj)
            else:
                parts.append(obj)
        
        return parts

    def load_shapes(self, selection, is_reloading_layout=False, initial_quantities=None, 
                     initial_overrides=None, initial_rotation_steps=None,
                     initial_up_directions=None, initial_fill_sheet=None):
        """Loads a selection of shapes into the UI."""
        self.ui.nest_button.setEnabled(True)
        
        # Dictionary to store counts from selection
        selection_counts = {}

        # Extract individual parts from assemblies/groups
        if not is_reloading_layout:
            extracted = self._extract_parts_from_selection(selection)
            if extracted:
                # Count occurrences before deduping
                for obj in extracted:
                    if obj in selection_counts:
                        selection_counts[obj] += 1
                    else:
                        selection_counts[obj] = 1
                
                selection = extracted
                FreeCAD.Console.PrintMessage(f"  -> Extracted {len(selection)} parts from selection.\n")
        
        # Keep unique, preserve order
        self.ui.selected_shapes_to_process = list(dict.fromkeys(selection)) 
        
        if not is_reloading_layout:
            self.ui.current_layout = None
            self.ui.hidden_originals = list(self.ui.selected_shapes_to_process)
        
        self.ui.shape_table.setRowCount(len(self.ui.selected_shapes_to_process))
        for i, obj in enumerate(self.ui.selected_shapes_to_process):
            display_label = obj.Label
            if display_label.startswith("master_shape_"):
                display_label = display_label.replace("master_shape_", "")
            
            # Default to 1, or use selection count if available
            qty = selection_counts.get(obj, 1)
            
            # Allow initial_quantities to override (e.g. from saved layout)
            if initial_quantities and obj.Label in initial_quantities:
                qty = initial_quantities[obj.Label]
                
            steps = 4
            override = False
            if initial_rotation_steps and obj.Label in initial_rotation_steps:
                steps = initial_rotation_steps[obj.Label]
            if initial_overrides and obj.Label in initial_overrides:
                override = initial_overrides[obj.Label]
            
            up_dir = "Z+"
            if initial_up_directions and obj.Label in initial_up_directions:
                up_dir = initial_up_directions[obj.Label]
                
            fill = False
            if initial_fill_sheet and obj.Label in initial_fill_sheet:
                fill = initial_fill_sheet[obj.Label]

            # We assume _add_part_row is still on UI or moved to a public method on UI
            # Plan says it stays on UI but exposed. Let's assume it's publicly accessible as add_part_row now.
            if hasattr(self.ui, 'add_part_row'):
                 self.ui.add_part_row(i, display_label, quantity=qty, rotation_steps=steps, 
                                      override_rotation=override, up_direction=up_dir, fill_sheet=fill)
            elif hasattr(self.ui, '_add_part_row'):
                 # Fallback if I haven't renamed it yet (I should rename it in next step)
                 self.ui._add_part_row(i, display_label, quantity=qty, rotation_steps=steps, 
                                      override_rotation=override, up_direction=up_dir, fill_sheet=fill)
        
        self.ui.shape_table.resizeColumnsToContents()
        self.ui.status_label.setText(f"{len(selection)} unique object(s) selected. Specify quantities and nest.")

    def add_selected_shapes(self):
        """Adds the currently selected FreeCAD objects to the shape table."""
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            self.ui.status_label.setText("Select shapes in the 3D view or tree to add them.")
            return

        # Handle assemblies in selection
        extracted = self._extract_parts_from_selection(selection)
        selection_counts = {}
        if extracted:
            for obj in extracted:
                selection_counts[obj] = selection_counts.get(obj, 0) + 1
            selection = extracted

        existing_labels = [self.ui.shape_table.item(row, 0).text() for row in range(self.ui.shape_table.rowCount())]
        
        added_count = 0
        
        # Process unique objects from selection
        unique_selection = list(dict.fromkeys(selection))
        
        for obj in unique_selection:
            if obj.Label not in existing_labels:
                row_position = self.ui.shape_table.rowCount()
                self.ui.shape_table.insertRow(row_position)
                
                # Determine quantity from selection count
                qty = selection_counts.get(obj, 1)
                
                if hasattr(self.ui, 'add_part_row'):
                    self.ui.add_part_row(row_position, obj.Label, quantity=qty)
                elif hasattr(self.ui, '_add_part_row'):
                    self.ui._add_part_row(row_position, obj.Label, quantity=qty)
                    
                self.ui.selected_shapes_to_process.append(obj)
                added_count += 1
        
        self.ui.shape_table.resizeColumnsToContents()
        self.ui.status_label.setText(f"Added {added_count} new shape(s).")

        # Enable the nest button if any shapes are now in the table
        if self.ui.shape_table.rowCount() > 0:
            self.ui.nest_button.setEnabled(True)

    def remove_selected_shapes(self):
        """Removes the selected rows from the shape table."""
        selected_items = self.ui.shape_table.selectedItems()
        selected_rows = sorted(list(set(item.row() for item in selected_items)), reverse=True)
        for row in selected_rows:
            label_to_remove = self.ui.shape_table.item(row, 0).text()
            self.ui.selected_shapes_to_process = [obj for obj in self.ui.selected_shapes_to_process if obj.Label != label_to_remove]
            self.ui.shape_table.removeRow(row)
        self.ui.status_label.setText(f"Removed {len(selected_rows)} shape(s).")

        # Disable the nest button if the table is now empty
        if self.ui.shape_table.rowCount() == 0:
            self.ui.nest_button.setEnabled(False)

    def _get_rotation_steps(self):
        """Returns the orientation count based on algorithm-specific angle mapping."""
        algo = self.ui.algorithm_dropdown.currentText()
        
        if algo == "Physics":
            idx = self.ui.physics_rotation_steps_slider.value()
            # Mapping: 360(1), 90(4), 45(8), 30(12), 15(24), 10(36), 5(72), 2(180), 1(360)
            angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]
            if idx < len(angles):
                angle = angles[idx]
                return int(360 / angle)
        else:
            # Minkowski mapping
            idx = self.ui.minkowski_rotation_steps_slider.value()
            angles = self.ui.rotation_angles
            if idx < len(angles):
                angle = angles[idx]
                return int(360 / angle)
        return 1

    def _execute_ga_nesting(self, target_layout, ui_params, quantities, master_map, 
                            rotation_params, algo_kwargs, is_simulating):
        """GA optimization using multiple layouts."""
        coordinator = GACoordinator(
            doc=self.doc,
            shape_preparer=self.shape_preparer,
            ui_callbacks={
                'set_status': lambda msg: self.ui.status_label.setText(msg),
                'update_progress': lambda c, t, m: self.ui.update_progress(c, t, m),
                'reset_progress': lambda: self.ui.reset_progress(),
                'play_sound': lambda: QtGui.QApplication.beep() if self.ui.sound_checkbox.isChecked() else None,
            }
        )
        self.current_job = coordinator.run(
            target_layout, ui_params, quantities, master_map,
            rotation_params, algo_kwargs, is_simulating
        )
    
    def finalize_job(self):
        """Called when User clicks OK."""
        if self.current_job:
            final_layout = self.current_job.commit()
            
            # Update UI reference so toggle_bounds works on the new layout
            self.ui.current_layout = final_layout
            
            # Ensure layout is visible and MasterShapes is hidden
            if final_layout and hasattr(final_layout, "ViewObject"):
                final_layout.ViewObject.Visibility = True
                
            if final_layout and hasattr(final_layout, "Group"):
                for child in final_layout.Group:
                    if child.Label.startswith("MasterShapes") and hasattr(child, "ViewObject"):
                        child.ViewObject.Visibility = False
                    elif child.Label.startswith("Sheet_") and hasattr(child, "ViewObject"):
                        child.ViewObject.Visibility = True
            
            self.current_job = None
            FreeCAD.Console.PrintMessage("Job Finalized & Committed.\n")
            self.doc.recompute()

    def request_cancel(self):
        """Called when the custom Cancel Nesting button is clicked."""
        if self.is_running:
            self.cancel_requested = True
            try:
                self.ui.status_label.setText("Cancelling... Please wait.")
            except Exception:
                pass
        else:
            self.cancel_job()
            if hasattr(self.ui, 'reject'):
                self.ui.reject()

    def _check_cancel(self):
        return self.cancel_requested

    def cancel_job(self):
        """Called when User clicks Cancel."""
        if self.current_job:
            # Capture target and ensure it's not deleted during cleanup
            target = self.current_job.target_layout
            
            # Run cleanup
            self.current_job.cleanup()
            
            # Restore visibility of original target
            if target:
                try: 
                    # Check if target layout is empty (newly created, never committed to)
                    has_content = any(
                        child.Label.startswith("Sheet_") or child.Label.startswith("MasterShapes")
                        for child in (target.Group if hasattr(target, "Group") else [])
                    )
                    
                    if not has_content:
                        # Empty layout - was created by _ensure_target_layout but never used
                        recursive_delete(self.doc, target)
                        if hasattr(self.ui, 'current_layout') and self.ui.current_layout == target:
                            self.ui.current_layout = None
                        FreeCAD.Console.PrintMessage("Removed empty target layout.\n")
                    else:
                        # Has content - restore visibility
                        if hasattr(target, "ViewObject"):
                            target.ViewObject.Visibility = True
                        
                        if hasattr(target, "Group"):
                            for child in target.Group:
                                # Show Sheets
                                if child.Label.startswith("Sheet_") and hasattr(child, "ViewObject"):
                                    child.ViewObject.Visibility = True
                                # Hide MasterShapes
                                if child.Label.startswith("MasterShapes") and hasattr(child, "ViewObject"):
                                    child.ViewObject.Visibility = False
                except Exception as e:
                    FreeCAD.Console.PrintWarning(f"[NestingController] Cancel cleanup failed for child: {e}\n")
            
            self.current_job = None
            FreeCAD.Console.PrintMessage("Job Cancelled.\n")
            self.doc.recompute()
    
    def toggle_bounds_visibility(self):
        is_visible = self.ui.show_bounds_checkbox.isChecked()
        
        # If a job is active, use its temp_layout (where current results are)
        # Otherwise use the committed current_layout
        if self.current_job and self.current_job.temp_layout:
            target_layout = self.current_job.temp_layout
        else:
            target_layout = getattr(self.ui, 'current_layout', None)
        
        if not target_layout: 
            return
        
        found_count = 0
        
        # Recursively find and toggle bounds visibility
        def set_show_bounds(obj, depth=0):
            nonlocal found_count
            indent = "  " * depth
            
            # Check for boundary objects that are children (by label)
            if obj.Label.startswith("boundary_"):
                found_count += 1
                if hasattr(obj, "ViewObject"):
                    obj.ViewObject.Visibility = is_visible
                    
            # Check for linked BoundaryObject property
            if hasattr(obj, "BoundaryObject") and obj.BoundaryObject:
                found_count += 1
                if hasattr(obj.BoundaryObject, "ViewObject"):
                    obj.BoundaryObject.ViewObject.Visibility = is_visible
                
            # Recurse into children
            if hasattr(obj, "Group"):
                for child in obj.Group:
                    set_show_bounds(child, depth + 1)
                    
        set_show_bounds(target_layout)
        self.doc.recompute()

    def _ensure_target_layout(self):
        """Determines the target layout, creating a default one if none exists."""
        target = getattr(self.ui, 'current_layout', None)
        
        # Validate existing
        if target:
            try:
                if target not in self.doc.Objects: target = None
            except Exception as e:
                FreeCAD.Console.PrintWarning(f"[NestingController] Target validation failed: {e}\n")
                target = None
            
        # Infer from selection
        if not target and hasattr(self.ui, 'selected_shapes_to_process') and self.ui.selected_shapes_to_process:
             # Logic to find parent layout derived previously...
             # Simplified for brevity/robustness
             pass 

        # Create Default
        if not target:
            base_name = "Layout"
            i = 0
            existing_labels = [o.Label for o in self.doc.Objects]
            while f"{base_name}_{i:03d}" in existing_labels: i += 1
            target = self.doc.addObject("App::DocumentObjectGroup", f"{base_name}_{i:03d}")
            target.Label = f"{base_name}_{i:03d}"
            self.ui.current_layout = target
            
        return target

    def _collect_ui_params(self):
        deflection_angle = self.ui.deflection_input.value()
        deflection_mm = deflection_angle / 200.0
        
        settings_dict = {
            'sheet_width': self.ui.sheet_width_input.value(),
            'sheet_height': self.ui.sheet_height_input.value(),
            'spacing': self.ui.part_spacing_input.value(),
            'sheet_thickness': self.ui.sheet_thickness_input.value(),
            'deflection': deflection_mm,  # Linear deflection for processing
            'deflection_angle': deflection_angle,  # Angle for persistence
            'simplification': self.ui.simplification_input.value(),
            # Rotation steps calculation
            'rotation_steps': self._get_rotation_steps(),
            'add_labels': self.ui.add_labels_checkbox.isChecked(),
            'font_path': getattr(self.ui, 'selected_font_path', None),
            'show_bounds': self.ui.show_bounds_checkbox.isChecked(),
            'label_height': self.ui.label_height_input.value(),
            'label_size': self.ui.label_size_input.value(),
            'generations': self.ui.minkowski_generations_input.value(),
            'population_size': self.ui.minkowski_population_size_input.value(),
            'use_gpu': self.ui.use_gpu_checkbox.isChecked(),
            'verbose': self.ui.verbose_logging_checkbox.isChecked(),
            'nesting_direction': self.ui.minkowski_direction_dial.value(),
            'algorithm': self.ui.algorithm_dropdown.currentText(),
            'stability_tolerance': self.ui.physics_improvement_threshold_input.value(),
            'anneal_curve': self.ui.physics_anneal_curve_type.currentText(),
            'anneal_min_amp': self.ui.physics_anneal_min_amp.value(),
            'anneal_max_amp': self.ui.physics_anneal_max_amp.value(),
            'anneal_rot_steps': self.ui.physics_anneal_rot_steps.value(),
            'anneal_rot_curve': self.ui.physics_anneal_rot_curve_type.currentText(),
            'anneal_rot_min': self.ui.physics_anneal_rot_min.value(),
            'anneal_rot_max': self.ui.physics_anneal_rot_max.value()
        }
        
        # Save persistence
        self.save_settings(settings_dict)
        
        return settings_dict

    def save_settings(self, settings):
        """Saves current UI settings to FreeCAD preferences."""
        prefs = FreeCAD.ParamGet(PREFS_PATH)
        prefs.SetFloat(PROP_SHEET_WIDTH, float(settings['sheet_width']))
        prefs.SetFloat(PROP_SHEET_HEIGHT, float(settings['sheet_height']))
        prefs.SetFloat(PROP_PART_SPACING, float(settings['spacing']))
        prefs.SetFloat(PROP_SHEET_THICKNESS, float(settings['sheet_thickness']))
        prefs.SetFloat(PROP_DEFLECTION_ANGLE, float(settings.get('deflection_angle', 10)))  # Save angle, not mm
        prefs.SetFloat(PROP_SIMPLIFICATION, float(settings['simplification']))
        
        # Save both isolated rotation settings
        mink_steps = int(360 / self.ui.rotation_angles[self.ui.minkowski_rotation_steps_slider.value()])
        prefs.SetInt("MinkowskiRotationSteps", mink_steps)
        
        phys_angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]
        phys_steps = int(360 / phys_angles[self.ui.physics_rotation_steps_slider.value()])
        prefs.SetInt("PhysicsRotationSteps", phys_steps)

        prefs.SetBool(PROP_ADD_LABELS, bool(settings['add_labels']))
        prefs.SetBool(PROP_SHOW_BOUNDS, bool(settings['show_bounds']))
        prefs.SetFloat(PROP_LABEL_HEIGHT, float(settings['label_height']))
        prefs.SetFloat(PROP_LABEL_SIZE, float(settings['label_size']))
        prefs.SetBool(PROP_USE_GPU, bool(settings.get('use_gpu', False)))
        prefs.SetFloat("PhysicsStabilityTolerance", float(settings.get('stability_tolerance', 0.01)))
        prefs.SetString("PhysicsAnnealCurveType", str(settings.get('anneal_curve', "Logarithmic")))
        prefs.SetFloat("PhysicsAnnealMinAmp", float(settings.get('anneal_min_amp', 0.1)))
        prefs.SetFloat("PhysicsAnnealMaxAmp", float(settings.get('anneal_max_amp', 100.0)))
        
        prefs.SetInt("PhysicsAnnealRotSteps", int(settings.get('anneal_rot_steps', 10)))
        prefs.SetString("PhysicsAnnealRotCurveType", str(settings.get('anneal_rot_curve', "Logarithmic")))
        prefs.SetFloat("PhysicsAnnealRotMin", float(settings.get('anneal_rot_min', 1.0)))
        prefs.SetFloat("PhysicsAnnealRotMax", float(settings.get('anneal_rot_max', 90.0)))
        if settings['font_path']:
             prefs.SetString("FontPath", str(settings['font_path']))

    def _collect_job_parameters(self, ui_settings):
        # Re-implementation of collecting quantities and master map from UI table
        quantities = {}
        master_map = {}
        rotation_params = {}
        
        global_rot = ui_settings['rotation_steps']
        
        for row in range(self.ui.shape_table.rowCount()):
            try:
                label = self.ui.shape_table.item(row, 0).text()
                qty = self.ui.shape_table.cellWidget(row, 1).value()
                
                rot_widget = self.ui.shape_table.cellWidget(row, 2)
                rot_val = rot_widget.findChild(QtGui.QSpinBox).value()
                override = self.ui.shape_table.cellWidget(row, 3).isChecked()
                
                # Get new parameters
                up_dir_combo = self.ui.shape_table.cellWidget(row, 4)
                up_direction = up_dir_combo.currentText() if up_dir_combo else "Z+"
                
                fill_checkbox = self.ui.shape_table.cellWidget(row, 5)
                fill_sheet = fill_checkbox.isChecked() if fill_checkbox else False
                
                # Store quantity with effective rotation (based on override) and new params
                quantities[label] = {
                    'quantity': qty,
                    'rotation_steps': rot_val if override else global_rot,
                    'up_direction': up_direction,
                    'fill_sheet': fill_sheet
                }
                
                # Store rotation params (value AND override flag) for persistence
                rotation_params[label] = (rot_val, override)
            except Exception as e:
                FreeCAD.Console.PrintWarning(f"[NestingController] Skipping row {row} in shape table: {e}\n")
                continue
            
        # Map objects
        for obj in self.ui.selected_shapes_to_process:
             try:
                 lbl = obj.Label.replace("master_shape_", "")
                 if lbl in quantities:
                     master_map[obj.Label] = obj
             except Exception as e:
                 FreeCAD.Console.PrintWarning(f"[NestingController] Failed to map object {obj.Label if hasattr(obj, 'Label') else 'unknown'}: {e}\n")
             
        return ui_settings, quantities, master_map, rotation_params

    def _prepare_algo_kwargs(self, ui_params):
        algo_kwargs = {}
        algorithm = ui_params.get('algorithm', 'Minkowski')
        
        if algorithm == 'Physics':
            if self.ui.physics_random_checkbox.isChecked():
                algo_kwargs['physics_direction'] = None 
            else:
                # Dial value is CCW from 6 o'clock. 
                # 0=Down(0,-1), 90=Left(-1,0), 180=Up(0,1), 270=Right(1,0)
                angle_deg = (270 - self.ui.physics_direction_dial.value()) % 360
                angle_rad = math.radians(angle_deg)
                algo_kwargs['physics_direction'] = (math.cos(angle_rad), math.sin(angle_rad))
            
            algo_kwargs['step_size'] = self.ui.physics_step_size_input.value()
            algo_kwargs['max_spawn_count'] = self.ui.physics_max_spawn_input.value()
            algo_kwargs['max_nesting_steps'] = self.ui.physics_max_nesting_steps_input.value()
            algo_kwargs['anneal_steps'] = self.ui.physics_anneal_steps_input.value()
            algo_kwargs['anneal_rotate_enabled'] = self.ui.anneal_rotate_checkbox.isChecked()
            algo_kwargs['anneal_translate_enabled'] = self.ui.anneal_translate_checkbox.isChecked()
            algo_kwargs['anneal_random_shake_direction'] = self.ui.anneal_random_shake_checkbox.isChecked()
            algo_kwargs['stability_tolerance'] = ui_params.get('stability_tolerance', 0.01)
            algo_kwargs['anneal_curve'] = ui_params.get('anneal_curve', "Logarithmic")
            algo_kwargs['anneal_min_amp'] = ui_params.get('anneal_min_amp', 0.1)
            algo_kwargs['anneal_max_amp'] = ui_params.get('anneal_max_amp', 100.0)
            algo_kwargs['anneal_rot_steps'] = ui_params.get('anneal_rot_steps', 10)
            algo_kwargs['anneal_rot_curve'] = ui_params.get('anneal_rot_curve', "Logarithmic")
            algo_kwargs['anneal_rot_min'] = ui_params.get('anneal_rot_min', 1.0)
            algo_kwargs['anneal_rot_max'] = ui_params.get('anneal_rot_max', 90.0)
        else:
            if self.ui.minkowski_random_checkbox.isChecked():
                algo_kwargs['search_direction'] = None
            else:
                angle_deg = (270 - self.ui.minkowski_direction_dial.value()) % 360
                angle_rad = math.radians(angle_deg)
                algo_kwargs['search_direction'] = (math.cos(angle_rad), math.sin(angle_rad))
            
            algo_kwargs['population_size'] = self.ui.minkowski_population_size_input.value()
            algo_kwargs['generations'] = self.ui.minkowski_generations_input.value()
            algo_kwargs['clear_nfp_cache'] = self.ui.clear_cache_checkbox.isChecked()
            algo_kwargs['use_gpu'] = ui_params.get('use_gpu', False)

        algo_kwargs['spacing'] = ui_params['spacing']
        
        if hasattr(self.ui, 'log_message'):
            algo_kwargs['log_callback'] = self.ui.log_message
            
        return algo_kwargs

    def install_taichi(self):
        """Installs the taichi library using pip in the current environment."""
        import sys
        import subprocess
        
        reply = QtGui.QMessageBox.question(
            self.ui, 
            "Install Dependencies?", 
            "This will attempt to install the 'taichi' library using pip.\n\n"
            "This may take a moment and requires an internet connection.\n"
            "FreeCAD might need to be restarted afterwards.\n\n"
            "Proceed?", 
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No
        )
        
        if reply == QtGui.QMessageBox.No:
            return

        try:
            self.ui.status_label.setText("Installing Dependencies...")
            if hasattr(self.ui, 'install_taichi_button'):
                self.ui.install_taichi_button.setEnabled(False)
            FreeCADGui.updateGui()
            
            # sys.executable in FreeCAD often points to FreeCAD.exe.
            # We need the python.exe in the same directory (bin).
            bin_dir = os.path.dirname(sys.executable)
            python_exe = sys.executable
            
            # Search for a better executable for pip if sys.executable is 'freecad'
            # Look for python.exe, python3, python, or FreeCADCmd
            for exe in ["python.exe", "python3", "python", "FreeCADCmd"]:
                exe_path = os.path.join(bin_dir, exe)
                if os.path.exists(exe_path):
                    python_exe = exe_path
                    break

            # Run pip install
            # Use --no-warn-script-location to avoid warnings about PATH
            cmd = [python_exe, "-m", "pip", "install", "taichi", "--user", "--no-warn-script-location"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                error_msg = f"Command failed with exit code {result.returncode}.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                raise Exception(error_msg)
            
            FreeCAD.Console.PrintMessage("Successfully installed dependencies.\n")
            self.ui.status_label.setText("Dependencies Installed!")
            if hasattr(self.ui, 'install_taichi_button'):
                self.ui.install_taichi_button.setText("Dependencies Installed")
            
            QtGui.QMessageBox.information(self.ui, "Success", "Dependencies installed successfully!\nPlease restart FreeCAD to ensure they load correctly.")
            
        except subprocess.CalledProcessError as e:
            FreeCAD.Console.PrintError(f"Failed to install dependencies: {e}\n")
            self.ui.status_label.setText("Installation Failed")
            if hasattr(self.ui, 'install_taichi_button'):
                self.ui.install_taichi_button.setEnabled(True)
            QtGui.QMessageBox.critical(self.ui, "Error", f"Failed to install dependencies.\nCheck the Report View for details.\n\nError: {e}")
        except Exception as e:
            FreeCAD.Console.PrintError(f"Error installing taichi: {e}\n")
            self.ui.status_label.setText("Error")
            if hasattr(self.ui, 'install_taichi_button'):
                self.ui.install_taichi_button.setEnabled(True)

