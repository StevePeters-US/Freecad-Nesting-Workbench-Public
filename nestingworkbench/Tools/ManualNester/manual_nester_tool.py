# Nesting/nestingworkbench/Tools/ManualNester/manual_nester_tool.py

"""
This module contains the ManualNesterToolObserver class, which implements a
simple drag-and-drop functionality for manually nesting parts in a layout.
"""

import FreeCAD
import FreeCADGui
from PySide import QtCore
import math
from .ui_manual_nester import ManualNesterToolUI
from .physics_engine import PhysicsEngine
from .collision_resolver import CollisionResolver

try:
    from pivy import coin
except ImportError:
    coin = None

class ManualNesterToolObserver:
    """
    A ViewObserver that captures mouse events to allow manual nesting (dragging)
    of parts within a selected layout group.
    """
    def __init__(self, view, panel_manager):
        self.panel_manager = panel_manager
        self.view = view
        self.pressed = False
        self.obj_to_move = None
        self.start_pos = None
        self.start_placement = None
        self.layout_group = None
        self.master_group = None
        self.new_objects = [] # Track objects created during this session
        self.original_placements = {}
        self.original_visibilities = {}
        self.callback_ids = []  # Store callback IDs for cleanup
        self.last_log_time = 0
        self.selected_obj = None
        self.mode = "IDLE" # IDLE, TRANSLATE, ROTATE
        self.constraint = None # None, "X", "Y"
        self.constraint_lock_pos = None # Vector where the constraint was activated
        self.is_mouse_down = False
        self.last_down_time = 0.0
        self.is_implicit_drag = False
        self.is_free_grab = False  # M-B07: click-to-grab, click-to-drop mode
        self.drag_start_screen_pos = (0,0)
        self.last_known_screen_pos = (0,0)
        self.pre_drag_placements = {} # Track placements for undo/cancel (M-009)
        self.radius_indicator = None # M-010: Coin3D overlay for influence radius
        self.warned_missing_bounds = set() # M-B08: One-time debug warning for no-bounds parts

        # Physics initialization
        self.physics_engine = PhysicsEngine()
        self.collision_resolver = CollisionResolver()
        self.physics_enabled = True
        self.obj_to_sheet = {} # Track which sheet each object belongs to

        # Connect UI signals
        if hasattr(self.panel_manager, 'form'):
            ui = self.panel_manager.form
            # Initial sync
            self.physics_engine.radius = ui.radius_spin.value()
            self.physics_engine.curve_exponent = [1.0, 2.0, 3.0][ui.curve_dropdown.currentIndex()]
            self.physics_engine.strength = ui.strength_spin.value()
            self.physics_enabled = ui.physics_enabled_cb.isChecked()

            # Signal connections
            ui.physics_enabled_cb.stateChanged.connect(
                lambda state: setattr(self, 'physics_enabled', bool(state))
            )
            ui.radius_spin.valueChanged.connect(
                lambda val: setattr(self.physics_engine, 'radius', val)
            )
            ui.curve_dropdown.currentIndexChanged.connect(
                lambda idx: setattr(self.physics_engine, 'curve_exponent', [1.0, 2.0, 3.0][idx])
            )
            ui.strength_spin.valueChanged.connect(
                lambda val: setattr(self.physics_engine, 'strength', val)
            )

        # 1. Infer Layout Group
        selection = FreeCADGui.Selection.getSelection()
        if selection and selection[0].isDerivedFrom("App::DocumentObjectGroup") and (selection[0].Label.startswith("Layout_") or selection[0].Label == "Layout"):
            self.layout_group = selection[0]
        else:
            # Replicate _ensure_target_layout logic
            self.layout_group = self._discover_or_create_layout()

        if not self.layout_group:
            FreeCAD.Console.PrintWarning("Manual Nester: Could not find or create a Layout group.\n")
            return

        # 2. Ensure MasterShapes group exists and is visible
        self.master_group = self._get_or_create_master_group()
        if self.master_group and hasattr(self.master_group, "ViewObject"):
            self.original_visibilities[self.master_group] = self.master_group.ViewObject.Visibility
            self.master_group.ViewObject.Visibility = True

        # 3. Store original placements and manage visibility
        # Track objects in the layout
        self._track_layout_objects()
        
        # Track objects in MasterShapes for picking
        self._track_master_objects()

        # 4. Always add a fresh drop-zone sheet
        self._add_drop_zone_sheet()

        # After changing visibilities, we need to update the GUI to reflect them.
        FreeCADGui.updateGui()

        # Register event callbacks for mouse interaction
        if self.layout_group:
            cb_id = self.view.addEventCallback("SoMouseButtonEvent", self._make_callback("SoMouseButtonEvent"))
            self.callback_ids.append(("SoMouseButtonEvent", cb_id))
            cb_id = self.view.addEventCallback("SoLocation2Event", self._make_callback("SoLocation2Event"))
            self.callback_ids.append(("SoLocation2Event", cb_id))
            cb_id = self.view.addEventCallback("SoKeyboardEvent", self._make_callback("SoKeyboardEvent"))
            self.callback_ids.append(("SoKeyboardEvent", cb_id))
            FreeCAD.Console.PrintMessage(f"Manual Nester Activated on {self.layout_group.Label}. Drag parts to move/nest.\n")

    def _discover_or_create_layout(self):
        doc = self.view.getSceneGraph().getChild(0).getProperty("document").getValue() # Hack to get doc from view if needed, but FreeCAD.ActiveDocument is usually fine
        doc = FreeCAD.ActiveDocument 
        
        # Try finding existing layout
        for obj in doc.Objects:
            if obj.isDerivedFrom("App::DocumentObjectGroup") and obj.Label.startswith("Layout_"):
                return obj
        
        # Create new
        base_name = "Layout"
        i = 1
        existing_labels = [o.Label for o in doc.Objects]
        while f"{base_name}_{i:03d}" in existing_labels: i += 1
        layout = doc.addObject("App::DocumentObjectGroup", f"{base_name}_{i:03d}")
        layout.Label = f"{base_name}_{i:03d}"
        return layout

    def _get_or_create_master_group(self):
        master_shapes_group = None
        for child in self.layout_group.Group:
             if child.Label == "MasterShapes":
                 master_shapes_group = child
                 break
        
        if not master_shapes_group:
            # Check root of doc
            for obj in self.layout_group.Document.Objects:
                if obj.Label == "MasterShapes" and obj.isDerivedFrom("App::DocumentObjectGroup"):
                    return obj
            
            # Create if missing
            master_shapes_group = self.layout_group.Document.addObject("App::DocumentObjectGroup", "MasterShapes")
            master_shapes_group.Label = "MasterShapes"
            self.layout_group.addObject(master_shapes_group)
        
        return master_shapes_group

    def _track_layout_objects(self):
        """Walks the layout group and tracks all parts."""
        for sheet_group in self.layout_group.Group:
            if sheet_group.isDerivedFrom("App::DocumentObjectGroup") and sheet_group.Label.startswith("Sheet_"):
                # Ensure sheet boundary is visible
                sheet_boundary = next((obj for obj in sheet_group.Group if obj.Label.startswith("Sheet_Boundary_")), None)
                if sheet_boundary and hasattr(sheet_boundary, "ViewObject"):
                    self.original_visibilities[sheet_boundary] = sheet_boundary.ViewObject.Visibility
                    sheet_boundary.ViewObject.Visibility = True
                
                for sub_group in sheet_group.Group:
                    if sub_group.isDerivedFrom("App::DocumentObjectGroup") and sub_group.Label.startswith("Shapes_"):
                        for obj in sub_group.Group:
                            # Only track the HIGHEST level object in the Shapes group.
                            # Usually this is the App::Part or a standalone Part::Feature.
                            # We skip any object whose parent is also in this group.
                            is_top_level = True
                            if hasattr(obj, "InList"):
                                for parent in obj.InList:
                                    if parent in sub_group.Group:
                                        is_top_level = False
                                        break
                            
                            if is_top_level and (obj.TypeId == "App::Part" or hasattr(obj, "Shape")):
                                self._track_single_object(obj, sheet_group)
                
                # Make existing sheet boundary unselectable
                if sheet_boundary and hasattr(sheet_boundary, "ViewObject"):
                    if hasattr(sheet_boundary.ViewObject, "Selectable"):
                        self.original_visibilities[sheet_boundary.Name + "_selectable"] = sheet_boundary.ViewObject.Selectable
                        sheet_boundary.ViewObject.Selectable = False

    def _track_master_objects(self):
        """Tracks master shapes so we can identify them during picking."""
        if not self.master_group: return
        for obj in self.master_group.Group:
            # Master objects are usually App::Part containing a Part::Feature
            if obj.isDerivedFrom("App::Part") or hasattr(obj, "Shape"):
                # We don't store placement for masters in original_placements 
                # because we don't want to move them, but we might pick them.
                pass

    def _track_single_object(self, obj, sheet_group=None):
        self.original_placements[obj] = obj.Placement.copy()
        if sheet_group:
            self.obj_to_sheet[obj] = sheet_group
        
        if hasattr(obj, "ViewObject"):
            self.original_visibilities[obj] = obj.ViewObject.Visibility
            
            # Manage visibility of linked objects (BoundaryObject and LabelObject)
            replacement_shown = False
            if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject, "ViewObject"):
                self.original_visibilities[obj.BoundaryObject] = obj.BoundaryObject.ViewObject.Visibility
                obj.BoundaryObject.ViewObject.Visibility = True # Always show bounds in manual nester mode
                replacement_shown = True
            if hasattr(obj, "LabelObject") and obj.LabelObject and hasattr(obj.LabelObject, "ViewObject"):
                self.original_visibilities[obj.LabelObject] = obj.LabelObject.ViewObject.Visibility
                obj.LabelObject.ViewObject.Visibility = True # Always show label in manual nester mode
                replacement_shown = True
            
            # Hide the original 3D shape if we are showing a replacement
            if replacement_shown:
                obj.ViewObject.Visibility = False
            
            # Make sure sheets are UNSELECTABLE to prevent selection interference
            # (Handled in pick_object filtering too, but this helps the native draggers)
            if hasattr(obj, "ViewObject"):
                if hasattr(obj.ViewObject, "Selectable"):
                    obj.ViewObject.Selectable = True # Ensure parts ARE selectable


    def eventCallback(self, event_type, event_dict):
        """The main callback method for handling mouse and keyboard events."""
        try:
            if not self.layout_group:
                return False 
            
            # --- KEYBOARD HANDLING ---
            if event_type == "SoKeyboardEvent" and event_dict["State"] == "DOWN":
                key = event_dict["Key"]
                
                # Handling Key Strings from FreeCAD
                key = str(key).upper()
                
                # ESC - Cancel
                if key == "ESCAPE": 
                    self.cancel_operation()
                    return True
                
                # G/R - Removed modal triggers (Legacy)
                
                # X/Y - Constraint (Dynamic Activation Lock)
                if key == "X":
                    if self.mode == "TRANSLATE":
                        self.set_constraint("X")
                        return True
                if key == "Y":
                    if self.mode == "TRANSLATE":
                        self.set_constraint("Y")
                        return True
                    
                # ENTER or RETURN - Confirm (Legacy, but kept for implicit drags)
                if key in ["RETURN", "ENTER"]: 
                    self.finish_operation()
                    return True

            # --- MOUSE BUTTON HANDLING ---
            if event_type == "SoMouseButtonEvent":
                FreeCAD.Console.PrintMessage(f"\n[RAW MOUSE EVENT DICT]: {event_dict}\n")
                
                pos = event_dict.get("Position", (0, 0))
                btn = event_dict.get("Button")
                state = event_dict.get("State")
                
                if btn in ["BUTTON1", 1]: # Left Button
                    if state == "DOWN":
                        import time
                        current_time = time.time()
                        
                        # Guard against rapid repeat DOWN events
                        if self.is_mouse_down and (current_time - self.last_down_time < 0.2):
                             return True
                        self.last_down_time = current_time

                        # If FreeCAD lost our UP event while dragging, force a drop.
                        # IMPORTANT: Defer via QTimer to avoid modifying the Coin3D
                        # scene graph from within an event callback (causes access violation).
                        if self.is_mouse_down:
                             if self.is_implicit_drag or self.is_free_grab:
                                 FreeCAD.Console.PrintMessage("Manual Nester: Forcing drop (missed UP event).\n")
                                 QtCore.QTimer.singleShot(0, self._deferred_force_drop)
                                 return True

                        if event_dict.get("DoubleClick", False):
                            return True
                        
                        self.is_mouse_down = True
                        # Initial mode check
                        if event_dict.get("Shift", False):
                            self.set_mode("ROTATE")
                        else:
                            self.set_mode("TRANSLATE")
                            
                        self.handle_click(pos)
                        return True
                    else: # UP
                        if self.is_mouse_down:
                            FreeCAD.Console.PrintMessage("Manual Nester: Mouse UP received.\n")
                            self.is_mouse_down = False
                            self.handle_release()
                        return True
                
                elif btn in ["BUTTON2", "BUTTON3", 2, 3]: # Right Button (Cancel)
                    if state == "DOWN":
                        if self.mode != "IDLE" or self.is_free_grab:
                            self.cancel_operation()
                        return True
                    else: # UP
                         return True # Consume to prevent context menu
                
                # --- MOUSE WHEEL HANDLING: Ctrl+Scroll adjusts physics radius ---
                elif btn in ["BUTTON4", "BUTTON5", 4, 5]:
                    ctrl_held = event_dict.get("Ctrl", False) or event_dict.get("Control", False)
                    if state == "DOWN" and ctrl_held:
                        delta = 25.0 if btn in ["BUTTON4", 4] else -25.0
                        new_radius = max(25.0, min(2000.0, self.physics_engine.radius + delta))
                        self.physics_engine.radius = new_radius

                        # Sync to UI
                        if hasattr(self.panel_manager, 'form'):
                            self.panel_manager.form.radius_spin.setValue(new_radius)

                        # Update indicator if actively dragging/grabbing
                        active = (self.is_mouse_down and self.is_implicit_drag) or self.is_free_grab
                        if active:
                             self.handle_move(self.last_known_screen_pos, True,
                                             event_dict.get("Shift", False))
                        return True
                    # Without Ctrl, don't consume — let FreeCAD handle zoom

            # --- MOUSE MOVE HANDLING ---
            elif event_type == "SoLocation2Event":
                pos = event_dict["Position"]
                self.last_known_screen_pos = pos
                snap = event_dict.get("Ctrl", False) or event_dict.get("Control", False)
                shift = event_dict.get("Shift", False)
                self.handle_move(pos, snap, shift)

                if self.mode != "IDLE" or self.is_free_grab: return True
            

            return False

        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Event callback failed: {e}\n")
            return False

    def _deferred_force_drop(self):
        """Called via QTimer to safely handle a missed UP event outside the event callback."""
        try:
            if not self.layout_group:
                return
            self.handle_release()
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Deferred force-drop failed: {e}\n")
            # Reset to a safe state
            self.finish_operation()
            self.is_mouse_down = False

    def _deferred_add_object_to_group(self, shapes_group_name, selected_obj_name):
        try:
            doc = FreeCAD.ActiveDocument
            if self.layout_group and hasattr(self.layout_group, 'Document'):
                doc = self.layout_group.Document
            if doc:
                grp = doc.getObject(shapes_group_name)
                obj = doc.getObject(selected_obj_name)
                if grp and obj:
                    grp.addObject(obj)
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Deferred add failed: {e}\n")
                
    def _deferred_revert_single_object(self, obj_name):
        try:
            doc = FreeCAD.ActiveDocument
            if self.layout_group and hasattr(self.layout_group, 'Document'):
                doc = self.layout_group.Document
            if doc:
                obj = doc.getObject(obj_name)
                if obj:
                    if obj in self.new_objects:
                        self.new_objects.remove(obj)
                    doc.removeObject(obj_name)
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Deferred revert failed: {e}\n")

    def handle_click(self, pos):
        """On mouse down: Select object and start interaction."""

        # M-B07: If in free-grab mode, this click DROPS the part
        if self.is_free_grab and self.selected_obj:
            FreeCAD.Console.PrintMessage(f"Manual Nester: Attempting to place {self.selected_obj.Label}...\n")
            target_sheet = self._find_sheet_at_pos(self.selected_obj.Placement.Base)
            if target_sheet:
                shapes_group = next((c for c in target_sheet.Group if c.Label.startswith("Shapes_")), None)
                if shapes_group:
                    QtCore.QTimer.singleShot(0, lambda g=shapes_group.Name, o=self.selected_obj.Name: self._deferred_add_object_to_group(g, o))
                FreeCAD.Console.PrintMessage(f"Manual Nester: Deferred placement of {self.selected_obj.Label}.\n")
            else:
                if self.selected_obj in self.new_objects:
                    QtCore.QTimer.singleShot(0, lambda o=self.selected_obj.Name: self._deferred_revert_single_object(o))
                    FreeCAD.Console.PrintMessage("Dropped outside sheet: clone implicitly scheduled for removal.\n")
            self.is_free_grab = False
            self.finish_operation()
            return

        clicked_obj = self.pick_object(pos)
        FreeCAD.Console.PrintMessage(f"Manual Nester: Picked {clicked_obj.Label if clicked_obj else 'None'}\n")
        
        # Check if we clicked on a Master Shape
        is_master = False
        if clicked_obj:
            p = clicked_obj
            while p:
                if p == self.master_group:
                    is_master = True
                    break
                # Walk up parents
                if p.InList: p = p.InList[0]
                else: p = None
        
        if is_master:
            self.start_pos = self.view.getPoint(pos[0], pos[1])
            new_obj = self._clone_part_from_master(clicked_obj)
            if new_obj:
                clicked_obj = new_obj
                # Enter free-grab mode: clone follows cursor, next click drops it
                self.selected_obj = clicked_obj
                self.drag_start_screen_pos = pos
                self.start_placement = self.selected_obj.Placement.copy()
                self.set_mode("TRANSLATE")
                self.is_free_grab = True
                FreeCAD.Console.PrintMessage(f"Manual Nester: Created clone {clicked_obj.Label}. Click to place.\n")
            return

        if clicked_obj:
            self.selected_obj = clicked_obj
            FreeCAD.Console.PrintMessage(f"Manual Nester: Starting interaction with {clicked_obj.Label}\n")
            
            # Prepare for potential drag
            self.drag_start_screen_pos = pos
            self.start_pos = self.view.getPoint(pos[0], pos[1]) # 3D point
            self.start_placement = self.selected_obj.Placement.copy()
            self.is_implicit_drag = False # Will become true if moved
                
        else:
            # Clicked on empty space
            self.selected_obj = None

    def handle_move(self, pos, snap=False, shift_held=False):
        if not self.selected_obj or (not self.is_mouse_down and not self.is_free_grab):
            return

        # DYNAMIC MODE SWITCH: If Shift is held/released during drag, switch mode
        active_drag = self.is_implicit_drag or self.is_free_grab
        target_mode = "ROTATE" if shift_held else "TRANSLATE"
        if self.mode != target_mode and active_drag:
             # Capture current state as new base for the switch
             FreeCAD.Console.PrintMessage(f"Manual Nester: Mode switched to {target_mode} while dragging.\n")
             self.start_placement = self.selected_obj.Placement.copy()
             self.drag_start_screen_pos = pos
             self.start_pos = self.view.getPoint(pos[0], pos[1])
             self.set_mode(target_mode)

        # Check drag threshold if not already dragging (skip for free-grab)
        if not self.is_implicit_drag and not self.is_free_grab:
             dx = pos[0] - self.drag_start_screen_pos[0]
             dy = pos[1] - self.drag_start_screen_pos[1]
             if math.sqrt(dx*dx + dy*dy) > 5:
                 self.is_implicit_drag = True
                 FreeCAD.Console.PrintMessage(f"Manual Nester: Drag threshold met in {self.mode}\n")

        if not self.is_implicit_drag and not self.is_free_grab: return
        
        if self.mode == "TRANSLATE":
            if not self.start_pos: return
            
            current_pos = self.view.getPoint(pos[0], pos[1])
            move_vec = current_pos - self.start_pos
            move_vec.z = 0 # Project to XY plane for 2D nesting
            
            new_placement = self.start_placement.copy()
            new_pos = new_placement.Base + move_vec
            
            # Apply Dynamic Constraints
            if self.constraint == "X":
                # Lock Y to the position when X was pressed
                new_pos.y = self.constraint_lock_pos.y
            elif self.constraint == "Y":
                # Lock X to the position when Y was pressed
                new_pos.x = self.constraint_lock_pos.x
            
            # Integrate Physics
            drag_delta = new_pos - self.selected_obj.Placement.Base
            
            new_placement.Base = new_pos
            self.selected_obj.Placement = new_placement
            
            if drag_delta.Length > 0.001:
                self._apply_physics(drag_delta)
            
            # M-010: Show radius indicator
            if self.physics_enabled:
                self._show_radius_indicator(new_pos, self.physics_engine.radius)
            else:
                self._hide_radius_indicator()
            
        elif self.mode == "ROTATE":
            if not self.start_placement: return
            
            # Calculate rotation based on horizontal mouse movement from drag start
            current_x = pos[0]
            start_x = self.drag_start_screen_pos[0]
            delta_x = current_x - start_x
            
            sensitivity = 0.5 # Degrees per pixel
            angle_deg = delta_x * sensitivity
            
            # Snap logic (CTRL key)
            if snap:
                step = 45.0
                angle_deg = round(angle_deg / step) * step
            
            # Rotate around Z axis (2D nesting)
            rot = FreeCAD.Rotation(FreeCAD.Vector(0,0,1), angle_deg)
            
            new_placement = self.start_placement.copy()
            new_placement.Rotation = rot.multiply(self.start_placement.Rotation)
            self.selected_obj.Placement = new_placement
            
            # M-010: Show radius indicator even in rotation mode if physics active
            if self.physics_enabled:
                self._show_radius_indicator(self.selected_obj.Placement.Base, self.physics_engine.radius)

    def _apply_physics(self, drag_delta):
        """Push nearby parts based on proximity to the dragged part."""
        if not self.physics_engine or not self.physics_enabled:
            return

        drag_info = self._get_obj_phys_info(self.selected_obj)
        if not drag_info: return
        dragged_center, d_w, d_h = drag_info

        # Collect other parts and their centers/dims
        parts_info = []
        for obj in self.original_placements:
            if obj == self.selected_obj:
                continue
            info = self._get_obj_phys_info(obj)
            if info:
                c, w, h = info
                parts_info.append((obj, c, w, h))

        # Compute and apply displacements (using gap distance)
        displacements = self.physics_engine.compute_displacements(
            dragged_center, d_w, d_h, drag_delta, parts_info
        )
        
        displaced_objs = []
        for obj, displacement in displacements:
            if displacement.Length > 0.01:  # Skip negligible moves
                # M-009: Store pre-drag placement for undo if not already stored
                if obj not in self.pre_drag_placements:
                    self.pre_drag_placements[obj] = obj.Placement.copy()

                obj.Placement.Base = obj.Placement.Base + displacement
                displaced_objs.append(obj)

        # 2. Clamp the DRAGGED part to its sheet boundary
        dragged_sheet = self.obj_to_sheet.get(self.selected_obj)
        if dragged_sheet:
            boundary = next((c for c in dragged_sheet.Group if c.Label.startswith("Sheet_Boundary_")), None)
            if boundary and hasattr(boundary, "Shape") and hasattr(boundary.Shape, "BoundBox"):
                s_bb = boundary.Shape.BoundBox
                s_pos = boundary.Placement.Base
                global_sheet_bb = FreeCAD.BoundBox(
                    s_bb.XMin + s_pos.x, s_bb.YMin + s_pos.y, s_bb.ZMin,
                    s_bb.XMax + s_pos.x, s_bb.YMax + s_pos.y, s_bb.ZMax
                )
                self.collision_resolver.clamp_to_sheet(self.selected_obj, global_sheet_bb)

        # 3. Iteratively resolve all collisions in the layout to create chain reaction (Relaxation)
        all_tracked = [o for o in self.original_placements if o != self.selected_obj]

        for _ in range(3):
            any_moved = False

            # A. Resolve overlaps between dragged part and others (dragged part stays, others move)
            for obj in all_tracked:
                self.collision_resolver.separate_overlapping(obj, [self.selected_obj])

            for i, obj in enumerate(all_tracked):
                # B. Clamp to its persistent sheet (GLOBAL COORDS)
                sheet_group = self.obj_to_sheet.get(obj)
                if sheet_group:
                    boundary = next((c for c in sheet_group.Group if c.Label.startswith("Sheet_Boundary_")), None)
                    if boundary and hasattr(boundary, "Shape") and hasattr(boundary.Shape, "BoundBox"):
                        s_bb = boundary.Shape.BoundBox
                        s_pos = boundary.Placement.Base
                        global_sheet_bb = FreeCAD.BoundBox(
                            s_bb.XMin + s_pos.x, s_bb.YMin + s_pos.y, s_bb.ZMin,
                            s_bb.XMax + s_pos.x, s_bb.YMax + s_pos.y, s_bb.ZMax
                        )
                        if self.collision_resolver.clamp_to_sheet(obj, global_sheet_bb):
                             any_moved = True

                # C. Separate from neighbors (Symmetric push)
                for other in all_tracked[i+1:]:
                    if self.collision_resolver.resolve_bi_collision(obj, other):
                        any_moved = True

            if not any_moved: break

    def _get_shape_bbox(self, obj, parent_placement=None):
        """Returns the global BoundBox for an object, prioritizing BoundaryObject."""
        # Accumulate placement through the hierarchy
        if parent_placement is None:
            current_placement = obj.Placement
        else:
            current_placement = parent_placement.multiply(obj.Placement)

        # 1. Prioritize BoundaryObject link
        if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject.Shape, "BoundBox"):
            bb = obj.BoundaryObject.Shape.BoundBox
            # BoundaryObject placement is relative to its parent (obj)
            abs_pos = current_placement.multiply(obj.BoundaryObject.Placement).Base
            return FreeCAD.BoundBox(
                bb.XMin + abs_pos.x, bb.YMin + abs_pos.y, bb.ZMin,
                bb.XMax + abs_pos.x, bb.YMax + abs_pos.y, bb.ZMax
            )

        # 2. Check for raw Shape
        if hasattr(obj, "Shape") and hasattr(obj.Shape, "BoundBox"):
            bb = obj.Shape.BoundBox
            abs_pos = current_placement.Base
            return FreeCAD.BoundBox(
                bb.XMin + abs_pos.x, bb.YMin + abs_pos.y, bb.ZMin,
                bb.XMax + abs_pos.x, bb.YMax + abs_pos.y, bb.ZMax
            )

        # 3. Recurse into App::Part containers
        if hasattr(obj, "Group"):
            for child in obj.Group:
                result = self._get_shape_bbox(child, current_placement)
                if result:
                    return result

        # 4. Strictly no bounds: One-time debug warning
        if obj.Name not in self.warned_missing_bounds:
            FreeCAD.Console.PrintWarning(f"Manual Nester: Part '{obj.Label}' has no bounds (BoundaryObject or Shape) and will not participate in collisions.\n")
            self.warned_missing_bounds.add(obj.Name)
            
        return None

    def _get_obj_phys_info(self, obj):
        """Returns (center_vector, width, height) in layout-global coordinates. Returns None if no bounds."""
        bb = self._get_shape_bbox(obj)
        if not bb:
            return None
            
        center = FreeCAD.Vector((bb.XMin + bb.XMax) / 2.0, (bb.YMin + bb.YMax) / 2.0, 0)
        return center, bb.XLength, bb.YLength

    def handle_release(self):
        # In free-grab mode, mouse release does NOT place the part.
        # The next left-click will handle placement via handle_click.
        if self.is_free_grab:
            self.is_mouse_down = False
            return

        # Clicked on a part without dragging — no-op (just deselect).
        # Hold-to-drag is the only interaction for existing parts.
        # Free-grab is reserved for master clones (set in handle_click).
        if not self.is_implicit_drag and self.selected_obj:
            self.finish_operation()
            self.is_mouse_down = False
            return

        # Hold-and-drag release: place the part
        if self.is_implicit_drag:
            if self.selected_obj:
                FreeCAD.Console.PrintMessage(f"Manual Nester: Ending drag, attempting to place {self.selected_obj.Label}...\n")
                target_sheet_group = self._find_sheet_at_pos(self.selected_obj.Placement.Base)
                if target_sheet_group:
                    shapes_group = next((c for c in target_sheet_group.Group if c.Label.startswith("Shapes_")), None)
                    if shapes_group:
                        QtCore.QTimer.singleShot(0, lambda g=shapes_group.Name, o=self.selected_obj.Name: self._deferred_add_object_to_group(g, o))
                        FreeCAD.Console.PrintMessage("Manual Nester: Deferred drop onto sheet.\n")
                else:
                    if self.selected_obj in self.new_objects:
                        QtCore.QTimer.singleShot(0, lambda o=self.selected_obj.Name: self._deferred_revert_single_object(o))
                        FreeCAD.Console.PrintMessage("Dropped outside sheet: clone implicitly scheduled for removal.\n")

        self.finish_operation()
        self.is_mouse_down = False
        self.is_implicit_drag = False

    def _find_sheet_at_pos(self, pos):
        """Finds the sheet group containing the given point."""
        for sheet_group in self.layout_group.Group:
            if sheet_group.isDerivedFrom("App::DocumentObjectGroup") and sheet_group.Label.startswith("Sheet_"):
                # Check boundary
                boundary = next((obj for obj in sheet_group.Group if obj.Label.startswith("Sheet_Boundary_")), None)
                if boundary:
                    bb = boundary.Shape.BoundBox
                    # Account for boundary placement
                    if pos.x >= (bb.XMin + boundary.Placement.Base.x) and pos.x <= (bb.XMax + boundary.Placement.Base.x) and \
                       pos.y >= (bb.YMin + boundary.Placement.Base.y) and pos.y <= (bb.YMax + boundary.Placement.Base.y):
                        return sheet_group
        return None

    def set_mode(self, mode):
        self.mode = mode
        self.constraint = None 
        self.constraint_lock_pos = None
        if mode in ["TRANSLATE", "ROTATE"]:
             FreeCAD.Console.PrintMessage(f"Manual Nester: {mode} Mode (Release to Drop)\n")
             # Setup start state if not already
             if not hasattr(self, 'start_placement') or not self.start_placement:
                 if self.selected_obj:
                    self.start_placement = self.selected_obj.Placement.copy()
             
             # Capture screen pos if not set (e.g. key press without click)
             if not hasattr(self, 'drag_start_screen_pos') or not self.drag_start_screen_pos:
                 if hasattr(self, 'last_known_screen_pos'):
                     self.drag_start_screen_pos = self.last_known_screen_pos
                 else:
                     self.drag_start_screen_pos = (0,0) # Fallback

    def set_constraint(self, constraint):
        """Toggle an axis constraint based on current position."""
        if self.constraint == constraint:
            self.constraint = None
            self.constraint_lock_pos = None
            FreeCAD.Console.PrintMessage("Constraint Cleared.\n")
        else:
            self.constraint = constraint
            # Lock based on CURRENT object position
            if self.selected_obj:
                self.constraint_lock_pos = self.selected_obj.Placement.Base.copy()
            FreeCAD.Console.PrintMessage(f"Constraint: {constraint}-Axis Locked.\n")

    def cancel_operation(self):
        if self.mode == "IDLE" and not self.is_free_grab:
            return

        try:
            if self.selected_obj and hasattr(self, 'start_placement') and self.start_placement:
                 try:
                     self.selected_obj.Placement = self.start_placement
                 except Exception:
                     pass
        except Exception:
            pass
             
        FreeCAD.Console.PrintMessage("Operation Cancelled.\n")
        
        # M-009: Revert physics-displaced parts
        try:
            if self.layout_group:
                for obj, placement in list(self.pre_drag_placements.items()):
                    try:
                        _ = obj.Name  # Trigger ReferenceError if C++ obj is deleted
                        obj.Placement = placement
                    except Exception:
                        pass
        except Exception:
            pass
            
        self.pre_drag_placements = {}
        
        self.mode = "IDLE"
        self.constraint = None
        self.constraint_lock_pos = None
        self.start_placement = None
        self.start_pos = None
        self.is_implicit_drag = False
        self.is_free_grab = False
        self.is_mouse_down = False
        self.selected_obj = None
        
        try:
            self._hide_radius_indicator() # M-010
        except Exception:
            pass

    def finish_operation(self):
        self.mode = "IDLE"
        self.selected_obj = None # Clear selection to prevent stickiness
        self.constraint = None
        self.constraint_lock_pos = None
        self.start_placement = None
        self.start_pos = None
        self.is_implicit_drag = False
        self.is_free_grab = False
        self.is_mouse_down = False
        self.pre_drag_placements = {} # M-009: Clear pre-drag placements
        try:
            self._hide_radius_indicator() # M-010
        except Exception:
            pass
        try:
            FreeCADGui.Selection.clearSelection() # Clear visual highlight
        except Exception:
            pass

    def pick_object(self, pos):
        """Helper to find the draggable object at screen pos."""
        info = self.view.getObjectInfo(pos)
        if info and "Object" in info:
             clicked_obj = info["Object"]
             # Resolve strings
             if isinstance(clicked_obj, str):
                 if self.layout_group and hasattr(self.layout_group, 'Document'):
                     clicked_obj = self.layout_group.Document.getObject(clicked_obj)
                 else:
                     clicked_obj = FreeCAD.ActiveDocument.getObject(clicked_obj)
             
             if not clicked_obj: return None
             
             parent_obj_from_click = info.get("ParentObject")
             # Resolve parent object if it's a string
             if isinstance(parent_obj_from_click, str):
                 parent_obj_from_click = FreeCAD.ActiveDocument.getObject(parent_obj_from_click)

             # FILTER: Ignore sheets and sheet boundaries
             if clicked_obj.Label.startswith("Sheet_"):
                 return None
             if parent_obj_from_click and parent_obj_from_click.Label.startswith("Sheet_"):
                 parent_obj_from_click = None

             draggable = self.get_draggable_parent(clicked_obj, parent_obj_from_click)
             if draggable:
                 FreeCAD.Console.PrintMessage(f"Manual Nester: Resolved draggable -> {draggable.Label}\n")
             return draggable
        return None

    def _make_callback(self, event_type):
        """Creates a callback wrapper that passes the event type to eventCallback."""
        def callback(event_dict):
            return self.eventCallback(event_type, event_dict)
        return callback

    def get_draggable_parent(self, obj, parent_obj_from_click=None):
        """
        Determines the actual object to drag based on what was clicked.
        Always returns the HIGHEST tracked container in the hierarchy.
        """        
        # 1. Walk up parents to find the highest tracked container
        highest_tracked = None
        p = obj
        while p:
             if p in self.original_placements:
                 highest_tracked = p # Keep updating to find the absolute highest tracked
                 
             if hasattr(p, "InList") and p.InList:
                 # Check all parents in InList (FreeCAD objects can have multiple parents/links)
                 found_higher = False
                 for parent in p.InList:
                     if parent in self.original_placements or any(anc in self.original_placements for anc in self._get_all_ancestors(parent)):
                         p = parent
                         found_higher = True
                         break
                 if not found_higher:
                     # If no tracked ancestor found in this branch, try walking up anyway
                     p = p.InList[0]
             else:
                 p = None

        if highest_tracked:
            return highest_tracked

        # 3. Check specific links (Boundary/Label) as fallback
        for tracked_obj in self.original_placements.keys():
            if hasattr(tracked_obj, "BoundaryObject") and tracked_obj.BoundaryObject == obj:
                return tracked_obj
            if hasattr(tracked_obj, "LabelObject") and tracked_obj.LabelObject == obj:
                return tracked_obj
            if hasattr(tracked_obj, "LinkedObject") and tracked_obj.LinkedObject == obj:
                return tracked_obj

        return None

    def _get_all_ancestors(self, obj):
        """Helper to get all ancestors of an object."""
        ancestors = set()
        stack = [obj]
        while stack:
            curr = stack.pop()
            if hasattr(curr, "InList"):
                for p in curr.InList:
                    if p not in ancestors:
                        ancestors.add(p)
                        stack.append(p)
        return ancestors

    def save_placements(self):
        """Saves the new placements (implicitly applied to objects)."""
        if not self.layout_group:
            return

        self._remove_empty_sheets()
        FreeCAD.Console.PrintMessage(f"Manual Nester: Saved new placements for objects.\n")
        # If sheets were stacked, this move breaks the "stacked" state
        if hasattr(self.layout_group, 'IsStacked') and self.layout_group.IsStacked:
            self.layout_group.IsStacked = False
            FreeCAD.Console.PrintWarning("Layout is no longer considered stacked due to manual adjustment.\n")

    def cancel(self):
        """Reverts any changes made to the object placements and removes new objects."""
        if not self.layout_group:
            return

        if self.original_placements:
            for obj, placement in self.original_placements.items():
                try:
                    if obj and obj.Name and obj in self.layout_group.Document.Objects:
                        obj.Placement = placement
                except Exception:
                    pass  # Object may already be deleted

        # Remove new objects and track deleted names to purge from tracking dicts
        deleted_names = set()
        for obj in reversed(self.new_objects):
            try:
                deleted_names.add(obj.Name)
                
                # PURGE from tracking dicts BEFORE deleting in C++
                self.original_placements.pop(obj, None)
                self.original_visibilities.pop(obj, None)
                
                self.layout_group.Document.removeObject(obj.Name)
            except Exception as e:
                pass # Can't safely log getattr if object is already dead
                
        self.new_objects = []

        FreeCAD.Console.PrintMessage("Manual Nester: Transformations cancelled and new items removed.\n")

    def _revert_single_object(self, obj):
        """Removes a single object and its related parts if it was newly created."""
        # Find container if needed
        # (Simplified: just remove by name if tracked)
        try:
             # If it's a container (App::Part), we should remove its children too? 
             # self.new_objects already contains children in order.
             if obj in self.new_objects:
                 self.layout_group.Document.removeObject(obj.Name)
                 self.new_objects.remove(obj)
                 if self.selected_obj == obj: self.selected_obj = None
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Failed to revert object {obj.Name}: {e}\n")
            pass

    def cleanup(self):
        """Removes the event callbacks from the view and restores original visibilities."""
        # Remove Coin3D radius indicator first
        self._hide_radius_indicator()

        for event_type, callback_id in self.callback_ids:
            try:
                self.view.removeEventCallback(event_type, callback_id)
            except Exception as e:
                FreeCAD.Console.PrintWarning(f"Could not remove {event_type} callback: {e}\n")
        self.callback_ids = []

        self.original_placements = {}

        # Restore sheet boundary selectability
        if self.layout_group and hasattr(self.layout_group, "Group"):
            for sheet_group in self.layout_group.Group:
                try:
                    if sheet_group.Label.startswith("Sheet_"):
                        boundary = next((obj for obj in sheet_group.Group if obj.Label.startswith("Sheet_Boundary_")), None)
                        if boundary and hasattr(boundary, "ViewObject"):
                            if hasattr(boundary.ViewObject, "Selectable"):
                                boundary.ViewObject.Selectable = True
                except Exception:
                    pass

        # Restore original visibilities — wrapped in try/except per object
        # because cancel() may have already deleted some objects
        for obj, is_visible in self.original_visibilities.items():
            try:
                if not isinstance(obj, str) and hasattr(obj, "Name") and obj.Name:
                    if hasattr(obj, "ViewObject") and obj.ViewObject:
                        obj.ViewObject.Visibility = is_visible
            except Exception:
                pass  # Object was already deleted at C++ level
        self.original_visibilities = {}

        FreeCADGui.updateGui()
        self.layout_group = None

    def _remove_empty_sheets(self):
        """Removes sheet groups that contain no parts in their Shapes_ sub-group."""
        doc = self.layout_group.Document
        sheets_to_remove = []
        for child in self.layout_group.Group:
            if child.isDerivedFrom("App::DocumentObjectGroup") and child.Label.startswith("Sheet_"):
                shapes_group = next((c for c in child.Group if c.Label.startswith("Shapes_")), None)
                if shapes_group and len(shapes_group.Group) == 0:
                    sheets_to_remove.append(child)

        for sheet_group in sheets_to_remove:
            label = sheet_group.Label
            # Remove children first (boundary, shapes group)
            for sub in reversed(sheet_group.Group):
                doc.removeObject(sub.Name)
            doc.removeObject(sheet_group.Name)
            FreeCAD.Console.PrintMessage(f"Manual Nester: Removed empty sheet '{label}'.\n")

    def _add_drop_zone_sheet(self):
        """Adds a fresh drop-zone sheet to the layout."""
        self._add_new_sheet()

    def _show_radius_indicator(self, center, radius):
        """M-010: Creates/updates a Coin3D indicator for the physics radius."""
        if not coin or not self.view:
            return

        if not self.radius_indicator:
            # Create the node tree
            self.radius_indicator = coin.SoSeparator()
            
            # Line style
            style = coin.SoDrawStyle()
            style.lineWidth = 1.0
            style.linePattern = 0xF0F0 # Dashed
            self.radius_indicator.addChild(style)
            
            # Color
            color = coin.SoBaseColor()
            color.rgb = (0.0, 0.5, 1.0) # Light blue
            self.radius_indicator.addChild(color)
            
            # Translation
            self.indicator_trans = coin.SoTranslation()
            self.radius_indicator.addChild(self.indicator_trans)
            
            # Circle coordinates
            self.indicator_coords = coin.SoCoordinate3()
            self.radius_indicator.addChild(self.indicator_coords)
            
            # Line set
            line_set = coin.SoLineSet()
            self.radius_indicator.addChild(line_set)
            
            # Add to view
            self.view.getSceneGraph().addChild(self.radius_indicator)

        # Update position
        self.indicator_trans.translation.setValue(center.x, center.y, center.z + 0.1) # Slightly above XY
        
        # Update circle geometry
        points = []
        segments = 64
        for i in range(segments + 1):
            angle = 2.0 * math.pi * i / segments
            points.append((radius * math.cos(angle), radius * math.sin(angle), 0))
        
        self.indicator_coords.point.setValues(0, len(points), points)

    def _hide_radius_indicator(self):
        """M-010: Removes the radius indicator from the view."""
        if self.radius_indicator and self.view:
            try:
                self.view.getSceneGraph().removeChild(self.radius_indicator)
            except Exception:
                pass  # Scene graph may already be torn down
            self.radius_indicator = None

    def _get_sheet_dimensions(self):
        """Returns (width, height) from the first existing sheet, or (1000, 1000) as default."""
        for child in self.layout_group.Group:
            if child.isDerivedFrom("App::DocumentObjectGroup") and child.Label.startswith("Sheet_"):
                boundary = next((c for c in child.Group if c.Label.startswith("Sheet_Boundary_")), None)
                if boundary and hasattr(boundary, "Shape"):
                    bb = boundary.Shape.BoundBox
                    return bb.XLength, bb.YLength
        return 1000.0, 1000.0

    def _add_new_sheet(self):
        """Adds a new sheet group with a boundary."""
        doc = self.layout_group.Document
        index = len([c for c in self.layout_group.Group if c.Label.startswith("Sheet_")]) + 1
        
        width, height = self._get_sheet_dimensions()
        
        sheet_group = doc.addObject("App::DocumentObjectGroup", f"Sheet_{index}")
        sheet_group.Label = f"Sheet_{index}"
        self.layout_group.addObject(sheet_group)
        
        # Add Boundary
        boundary = doc.addObject("Part::Feature", f"Sheet_Boundary_{index}")
        # Use dimensions from existing sheets
        import Part
        boundary.Shape = Part.makePlane(width, height)
        # Position it to the right of existing sheets if any (width + 10% gap)
        offset_x = (index - 1) * (width * 1.1)
        boundary.Placement = FreeCAD.Placement(FreeCAD.Vector(offset_x, 0, 0), FreeCAD.Rotation())
        sheet_group.addObject(boundary)
        
        # Add Shapes Group
        shapes_group = doc.addObject("App::DocumentObjectGroup", f"Shapes_{index}")
        shapes_group.Label = f"Shapes_{index}"
        sheet_group.addObject(shapes_group)
        
        if hasattr(boundary, "ViewObject"):
            boundary.ViewObject.Transparency = 75
            if hasattr(boundary.ViewObject, "Selectable"):
                boundary.ViewObject.Selectable = False # Make sheet unselectable natively
        
        self.new_objects.append(sheet_group)
        self.new_objects.append(boundary)
        self.new_objects.append(shapes_group)
        return sheet_group

    def _clone_part_from_master(self, master_obj):
        """Creates a clone of a master shape to be placed in the layout."""
        doc = self.layout_group.Document
        
        # 1. Identify identifying properties from Master container (App::Part)
        master_container = master_obj
        if not master_obj.isDerivedFrom("App::Part"):
            if master_obj.InList:
                for p in master_obj.InList:
                    if p.isDerivedFrom("App::Part"):
                        master_container = p
                        break
        
        # Find the actual shape object inside the master container
        master_shape_feature = None
        for child in master_container.Group:
            if child.Label.startswith("master_shape_"):
                master_shape_feature = child
                break
        if not master_shape_feature: master_shape_feature = master_obj

        # 2. Create the Nested Container (replicate NestingJob logic)
        part_label = master_container.Label.replace("master_", "")
        count = len(doc.findObjects(Label=f"nested_{part_label}_*")) + 1
        
        container = doc.addObject("App::Part", f"nested_{part_label}_{count}")
        container.Label = f"nested_{part_label}_{count}"
        
        # 3. Create Shape Object
        nested_part = doc.addObject("Part::Feature", f"part_{part_label}_{count}")
        nested_part.Shape = master_shape_feature.Shape.copy()
        nested_part.Placement = master_shape_feature.Placement.copy()
        container.addObject(nested_part)
        
        # 4. Copy Boundary if it exists
        if hasattr(master_shape_feature, "BoundaryObject") and master_shape_feature.BoundaryObject:
            bound_copy = doc.addObject("Part::Feature", f"boundary_{part_label}_{count}")
            bound_copy.Shape = master_shape_feature.BoundaryObject.Shape.copy()
            container.addObject(bound_copy)
            if not hasattr(nested_part, "BoundaryObject"):
                nested_part.addProperty("App::PropertyLink", "BoundaryObject", "Nesting", "Boundary object")
            nested_part.BoundaryObject = bound_copy
            if hasattr(bound_copy, "ViewObject"): bound_copy.ViewObject.Visibility = False
        
        # Track for revert
        self.new_objects.append(container)
        self.new_objects.append(nested_part)
        if hasattr(nested_part, "BoundaryObject") and nested_part.BoundaryObject:
            self.new_objects.append(nested_part.BoundaryObject)
            
        # Initial placement at cursor
        container.Placement = FreeCAD.Placement(self.start_pos, FreeCAD.Rotation())
        
        # Track for dragging
        self._track_single_object(container, None)
        return container
