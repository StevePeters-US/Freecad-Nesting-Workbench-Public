# Nesting/InitGui.py


import FreeCAD
import FreeCADGui
import os
import nestingworkbench

# Register the icon path at module level so it's available immediately
# Use nestingworkbench module location to reliably find the workbench root
wb_path = os.path.dirname(os.path.dirname(nestingworkbench.__file__))
icon_path = os.path.join(wb_path, 'Resources', 'icons')
FreeCADGui.addIconPath(icon_path)

class NestingWorkbench(FreeCADGui.Workbench):
    """
    Defines the Nesting Workbench.
    """
    MenuText = "Nesting"
    ToolTip = "A workbench for 2D nesting of shapes."
    Icon = "Nesting_Workbench.png"

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        """This function is executed when the workbench is activated."""
        # Import the command modules. This executes the FreeCADGui.addCommand()
        # in each file, making the commands available to FreeCAD.
        from nesting_commands import command_nest
        from nesting_commands import command_stack_sheets
        from nesting_commands import command_manual_nester
        from nesting_commands import command_export_sheets
        from nesting_commands import command_create_cam_job
        from nesting_commands import command_create_silhouette
        # Create Menu (Dropdown)
        self.appendMenu(["Nesting"], [
            'Nesting_Run',
            'Nesting_StackSheets',
            'Nesting_ManualNester',
            'Nesting_Export',
            'Nesting_CreateCAMJob',
            'Nesting_CreateSilhouette'
        ])
        self.appendToolbar("Nesting", [
            'Nesting_Run',
            'Nesting_StackSheets',
            'Nesting_ManualNester',
            'Nesting_Export',
            'Nesting_CreateCAMJob',
            'Nesting_CreateSilhouette'
        ])

    def Activated(self):
        """This function is executed when the workbench is activated."""
        return

    def Deactivated(self):
        """This function is executed when the workbench is deactivated."""
        return

# Add the workbench to FreeCAD's list of available workbenches
FreeCADGui.addWorkbench(NestingWorkbench())
