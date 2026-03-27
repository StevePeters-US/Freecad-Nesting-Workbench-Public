# Nesting/nestingworkbench/datatypes/sheet_object.py

"""
This module defines a custom FreeCAD scripted object for representing a sheet.
"""

import FreeCAD
import Part
from ..constants import *

class SheetObject:
    """A scripted object representing a single sheet of material."""

    def __init__(self, obj):
        """Called when a new object is created."""
        obj.Proxy = self
        obj.addProperty(PROP_LENGTH, PROP_SHEET_WIDTH, "Sheet", "The width of the sheet").SheetWidth = 600.0
        obj.addProperty(PROP_LENGTH, PROP_SHEET_HEIGHT, "Sheet", "The height of the sheet").SheetHeight = 600.0
        obj.ViewObject.Proxy = 0 # Make sure the default view provider is used

    def execute(self, fp):
        """Called on recompute."""
        # Create a plane based on the object's properties
        width = fp.SheetWidth
        height = fp.SheetHeight
        fp.Shape = Part.makePlane(width, height)

class ViewProviderSheet:
    """A view provider for the SheetObject."""

    def __init__(self, vobj):
        """Called when the view object is created."""
        vobj.Proxy = self

    def getIcon(self):
        """Return the icon for the sheet object in the tree view."""
        # You can create a specific icon for sheets later if you wish
        return """
            /* XPM */
            static char * sheet_icon_xpm[] = {
            "16 16 2 1",
            " 	c None",
            ".	c #808080",
            "................",
            ".              .",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................",
            "................"};
            """

    def attach(self, vobj):
        """Set up the view object's properties."""
        vobj.Transparency = 75
        vobj.ShapeColor = (0.8, 0.8, 1.0) # A light blue color

def create_sheet(name="Sheet"):
    """Helper function to create a new SheetObject in the active document."""
    doc = FreeCAD.ActiveDocument
    obj = doc.addObject("Part::FeaturePython", name)
    SheetObject(obj)
    if FreeCAD.GuiUp:
        ViewProviderSheet(obj.ViewObject)
    return obj