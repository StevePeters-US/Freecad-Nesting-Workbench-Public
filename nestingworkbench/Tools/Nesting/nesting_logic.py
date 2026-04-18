from PySide import QtGui
import FreeCAD
import FreeCADGui
import Part
import copy

from .algorithms import nesting_strategy
from .algorithms import physics_nester
from .visualization_manager import VisualizationManager

class NestingDependencyError(Exception):
    """Custom exception for missing optional dependencies like Shapely."""
    pass

try:
    # Check for shapely availability without importing specific functions
    import shapely
    from shapely.affinity import rotate, translate
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

# Global manager removed to improve testability and thread safety (CR-118)

def _visualize_trial_placement(part, angle, x, y, viz_manager):
    """Draws the boundary polygon at a trial position during simulation."""
    if not viz_manager: return
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    
    try:
        # Get the boundary polygon from the part
        if hasattr(part, 'polygon') and part.polygon:
            # Rotate and translate the polygon to the trial position
            rotated_poly = rotate(part.polygon, angle, origin='centroid')
            translated_poly = translate(rotated_poly, xoff=x, yoff=y)
            
            # Convert shapely polygon to FreeCAD wire
            coords = list(translated_poly.exterior.coords)
            points = [FreeCAD.Vector(c[0], c[1], 0) for c in coords]
            wire = Part.makePolygon(points)
            
            # Use the visualization manager to draw
            viz_manager.draw_trial_placement(doc, wire)
    except Exception as e:
        FreeCAD.Console.PrintWarning(f"[nesting_logic] Draw failed: {e}\n")

def _cleanup_trial_viz(viz_manager):
    """Removes the trial visualization object and simulation sheet boundaries."""
    if not viz_manager: return
    doc = FreeCAD.ActiveDocument
    viz_manager.clear_trial_placement(doc)

def _find_master_container_for_part(part):
    """Finds the master container corresponding to a part being placed."""
    doc = FreeCAD.ActiveDocument
    if not doc:
        return None
    
    # Get the base label (e.g., "O" from "O_1")
    base_label = part.id.rsplit('_', 1)[0] if '_' in part.id else part.id
    
    # Try both temp_master_ (during nesting) and master_ prefixes
    master_names = [f"temp_master_{base_label}", f"master_{base_label}"]
    
    # Search in Layout_temp first (active nesting), then other layouts
    for obj in doc.Objects:
        try:
            if hasattr(obj, "Group") and (obj.Label.startswith("Layout_temp") or obj.Label.startswith("Layout")):
                for child in obj.Group:
                    if child.Label == "MasterShapes" and hasattr(child, "Group"):
                        for master in child.Group:
                            if master.Label in master_names:
                                return master
        except RuntimeError:
            # Object might be deleted/invalid, skip it
            continue
    return None

def _on_part_start(part, viz_manager):
    """Called when starting to place a part - highlight the master shape's boundary."""
    if not viz_manager: return
    master_container = _find_master_container_for_part(part)
    if master_container:
        viz_manager.highlight_master(master_container)

def _on_part_end(part, placed, viz_manager):
    """Called after part is placed."""
    pass

def _cleanup_highlighting(viz_manager):
    """Called after nesting completes to ensure all highlighting is removed."""
    if viz_manager:
        viz_manager.clear_highlight()

# --- Public Function ---
def nest(parts, width, height, rotation_steps=1, simulate=False, algorithm='Minkowski', viz_manager=None, **kwargs):
    """
    Convenience function to run the nesting algorithm.
    """
    from ...datatypes.shape import Shape
    
    if kwargs.pop('clear_nfp_cache', False):
        Shape.clear_nfp_cache()

    sort = kwargs.pop('sort', True)
    parts_to_process = parts if simulate else copy.deepcopy(parts)

    steps = 0
    sheets = []
    unplaced = []

    if not SHAPELY_AVAILABLE:
        show_shapely_installation_instructions()
        raise NestingDependencyError("The selected algorithm requires the 'Shapely' library.")

    # If simulation is enabled, ensure we have a viz_manager and bind callbacks
    if simulate:
        if viz_manager is None:
            viz_manager = VisualizationManager()
            
        kwargs['trial_callback'] = lambda p, a, x, y: _visualize_trial_placement(p, a, x, y, viz_manager)
        kwargs['part_start_callback'] = lambda p: _on_part_start(p, viz_manager)
        kwargs['part_end_callback'] = lambda p, pl: _on_part_end(p, pl, viz_manager)

    if algorithm == 'Physics':
        nester = physics_nester.PhysicsNester(width, height, rotation_steps, **kwargs)
    else:
        nester = nesting_strategy.Nester(width, height, rotation_steps, **kwargs)

    if simulate:
        nester.update_callback = lambda part, sheet: (sheet.draw(FreeCAD.ActiveDocument, {}, transient_part=part), FreeCADGui.updateGui())

    import time
    start_time = time.monotonic()
    result = nester.nest(parts_to_process, sort=sort)
    elapsed = time.monotonic() - start_time
    
    if simulate:
        _cleanup_trial_viz(viz_manager)
        _cleanup_highlighting(viz_manager)
    
    if len(result) == 3:
        sheets, unplaced, steps = result
    else:
        sheets, unplaced = result

    _calculate_efficiency(sheets, verbose=kwargs.get('verbose', False))

    return sheets, unplaced, steps, elapsed

def _calculate_efficiency(sheets, verbose=False):
    """Calculates and displays sheet packing efficiency."""
    if not sheets:
        return
    
    total_parts_area = 0
    total_sheet_area = 0
    
    if verbose:
        FreeCAD.Console.PrintMessage("\n--- PACKING EFFICIENCY ---\n")
    
    for i, sheet in enumerate(sheets):
        sheet_area = sheet.width * sheet.height
        parts_area = sum(part.shape.area for part in sheet.parts if hasattr(part, 'shape') and part.shape)
        
        total_sheet_area += sheet_area
        total_parts_area += parts_area
        
        if verbose and sheet_area > 0:
            efficiency = (parts_area / sheet_area) * 100
            FreeCAD.Console.PrintMessage(f"  Sheet {i+1}: {efficiency:.1f}% ({parts_area:.0f} / {sheet_area:.0f} mm²)\n")
    
    if total_sheet_area > 0:
        overall_efficiency = (total_parts_area / total_sheet_area) * 100
        if verbose:
            FreeCAD.Console.PrintMessage(f"  Overall: {overall_efficiency:.1f}% ({total_parts_area:.0f} / {total_sheet_area:.0f} mm²)\n")
            FreeCAD.Console.PrintMessage("--------------------------\n")
        else:
            FreeCAD.Console.PrintMessage(f"Packing Efficiency: {overall_efficiency:.1f}%\n")

def show_shapely_installation_instructions():
    msg_box = QtGui.QMessageBox()
    msg_box.setIcon(QtGui.QMessageBox.Warning)
    msg_box.setWindowTitle("Shapely Library Not Found")
    msg_box.setText("The selected nesting algorithm requires the 'Shapely' library, but it is not installed.")
    msg_box.setInformativeText(
        "To use this algorithm, you need to install the 'shapely' library into FreeCAD's Python environment.\n\n"
        "1. **Find FreeCAD's Python Executable:**\n"
        "   Open the Python console in FreeCAD and run:\n"
        "   `import sys; print(sys.executable)`\n"
        "   Copy the path that is printed.\n\n"
        "2. **Open a Command Prompt:**\n"
        "   Open a Windows Command Prompt (cmd.exe).\n\n"
        "3. **Install Shapely:**\n"
        "   In the command prompt, use the path you copied to run the following command (don't forget the quotes):\n"
        "   `\"<path_to_python_exe>\" -m pip install shapely`\n\n"
        "After installation, please restart FreeCAD."
    )
    msg_box.setStandardButtons(QtGui.QMessageBox.Ok)
    msg_box.exec_()
