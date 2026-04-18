# Nesting/nesting/ui_nesting.py

"""
This module contains the NestingPanel class, which defines the user interface
for the main nesting task panel.
"""

from PySide import QtGui, QtCore
import FreeCAD
import FreeCADGui
import os
from ...constants import *

_MINKOWSKI_DIR_MAX = 359

_DEFAULTS = {
    "sheet_width": 600.0,
    "sheet_height": 600.0,
    "part_spacing": 12.5,
    "sheet_thickness": 3.0,
    "deflection_angle": 30.0,
    "verbose_logging": False,
    "rotation_angles": [360, 180, 120, 90, 45, 30, 15, 10, 5, 1],
}

class NestingPanel(QtGui.QWidget):
    """
    Defines the user interface for the main nesting task panel, including
    all input fields, buttons, and the table of shapes.
    """
    def __init__(self, parent=None):
        super(NestingPanel, self).__init__(parent)
        FreeCAD.Console.PrintMessage("NestingPanel initialized.\n")
        self.setWindowTitle("Nesting Tool")
        self.selected_shapes_to_process = []
        self.hidden_originals = []
        self.current_layout = None
        self.selected_font_path = ""
        self.initUI()
        self.set_default_font()
    
    def accept(self):
        """Called when the user clicks Standard Button OK / Apply."""
        if hasattr(self, 'controller'):
            self.controller.finalize_job()
        return True

    def reject(self):
        """Called when the user clicks Standard Button Cancel / Close."""
        if hasattr(self, 'controller'):
            self.controller.cancel_job()
            
        # Also ensure visibility is restored if controller didn't fully run
        for obj in self.hidden_originals:
             if hasattr(obj, "ViewObject"):
                 obj.ViewObject.Visibility = True
                 
        return True

    def initUI(self):
        main_layout = QtGui.QVBoxLayout()
        form_layout = QtGui.QFormLayout()
        
        # Algorithm Selection
        self.algorithm_dropdown = QtGui.QComboBox()
        self.algorithm_dropdown.addItems(["Minkowski", "Physics"])
        self.algorithm_dropdown.setCurrentIndex(0) # Default to Minkowski
        self.algorithm_dropdown.currentTextChanged.connect(self._on_algorithm_change)
        form_layout.addRow("Nesting Algorithm:", self.algorithm_dropdown)

        font_layout = QtGui.QHBoxLayout()
        table_button_layout = QtGui.QHBoxLayout()
        action_button_layout = QtGui.QHBoxLayout()

        self.sheet_width_input = QtGui.QDoubleSpinBox(); self.sheet_width_input.setRange(1, 10000); self.sheet_width_input.setValue(_DEFAULTS["sheet_width"])
        self.sheet_height_input = QtGui.QDoubleSpinBox(); self.sheet_height_input.setRange(1, 10000); self.sheet_height_input.setValue(_DEFAULTS["sheet_height"])
        self.sheet_thickness_input = QtGui.QDoubleSpinBox(); self.sheet_thickness_input.setRange(0.1, 1000); self.sheet_thickness_input.setValue(_DEFAULTS["sheet_thickness"])
        self.part_spacing_input = QtGui.QDoubleSpinBox(); self.part_spacing_input.setRange(0, 1000); self.part_spacing_input.setValue(_DEFAULTS["part_spacing"])
        
        # --- Advanced Boundary Settings ---
        # Deflection is now specified as an angle (degrees) for more intuitive control
        # Internally converted to linear deflection: deflection_mm = angle / 200.0
        self.deflection_input = QtGui.QDoubleSpinBox()
        self.deflection_input.setRange(1, 90)
        self.deflection_input.setValue(_DEFAULTS["deflection_angle"])  # 30° default for faster processing
        self.deflection_input.setSingleStep(1)
        self.deflection_input.setDecimals(0)
        self.deflection_input.setSuffix("°")
        self.deflection_input.setToolTip(
            "<b>Curve Angle (Tessellation Quality):</b><br>"
            "Maximum angular deviation when approximating curves.<br><br>"
            "<b>Smaller (5-10°):</b> Smoother curves, more points, slower.<br>"
            "<b>Larger (20-45°):</b> Coarser curves, fewer points, faster.<br><br>"
            "<i>Tip: 10° is good for most parts. Use 5° for precision, 30°+ for speed.</i>"
        )
        
        self.simplification_input = QtGui.QDoubleSpinBox(); self.simplification_input.setRange(0.001, 10.0); self.simplification_input.setValue(1.0); self.simplification_input.setSingleStep(0.1); self.simplification_input.setDecimals(3)
        self.simplification_input.setToolTip(
            "<b>Simplification (Point Reduction):</b><br>"
            "Tolerance (mm) for removing redundant boundary points.<br><br>"
            "<b>Smaller (0.1-0.5):</b> More detailed boundaries, slower nesting.<br>"
            "<b>Larger (1.0-5.0):</b> Simpler boundaries, faster nesting.<br><br>"
            "<i>Tip: Set this to your machine's precision tolerance (e.g., 1mm for routers).</i>"
        )


        self.shape_table = QtGui.QTableWidget()
        self.shape_table.setColumnCount(6)
        self.shape_table.setHorizontalHeaderLabels(["Shape", "Quantity", "Rotations", "Override", "Up Dir", "Fill"])

        # Angles: 360 (1 step), 180 (2), 120 (3), 90 (4), 45 (8), 30 (12), 15 (24), 10 (36), 5 (72), 1 (360)
        self.rotation_angles = _DEFAULTS["rotation_angles"]
        



        # --- Minkowski Packer Settings ---
        self.minkowski_settings_group = QtGui.QGroupBox("Minkowski Nesting Settings")
        minkowski_form_layout = QtGui.QFormLayout()

        # Direction Dial for Minkowski
        self.minkowski_direction_dial = QtGui.QDial()
        self.minkowski_direction_dial.setRange(0, _MINKOWSKI_DIR_MAX)
        self.minkowski_direction_dial.setValue(0) # Default to Down
        self.minkowski_direction_dial.setWrapping(True)
        self.minkowski_direction_dial.setNotchesVisible(True)
        self.minkowski_direction_label = QtGui.QLabel("Down")
        self.minkowski_direction_label.setAlignment(QtCore.Qt.AlignCenter)
        
        def update_minkowski_dial_label(value):
            direction_map = {0: "Down", 90: "Left", 180: "Up", 270: "Right"}
            direction_text = direction_map.get(value, "")
            self.minkowski_direction_label.setText(direction_text if direction_text else f"{value}°")
        self.minkowski_direction_dial.valueChanged.connect(update_minkowski_dial_label)

        minkowski_dial_layout = QtGui.QVBoxLayout()
        minkowski_dial_layout.addWidget(self.minkowski_direction_dial)
        minkowski_dial_layout.addWidget(self.minkowski_direction_label)

        # Random Direction Checkbox for Minkowski
        self.minkowski_random_checkbox = QtGui.QCheckBox("Use Random Strategy")
        self.minkowski_random_checkbox.setToolTip("If checked, each part will use a randomized placement weighting.")
        self.minkowski_random_checkbox.stateChanged.connect(lambda state: self.minkowski_direction_dial.setDisabled(state))

        minkowski_form_layout.addRow("Nesting Direction:", minkowski_dial_layout)
        minkowski_form_layout.addRow(self.minkowski_random_checkbox)
        
        self.clear_cache_checkbox = QtGui.QCheckBox("Clear NFP Cache")
        self.clear_cache_checkbox.setChecked(False)
        self.clear_cache_checkbox.setToolTip("Forces recalculation of No-Fit Polygons. Slower, but resolves potential caching issues.")
        minkowski_form_layout.addRow(self.clear_cache_checkbox)

        # GPU Acceleration Checkbox
        gpu_layout = QtGui.QHBoxLayout()
        self.use_gpu_checkbox = QtGui.QCheckBox("Enable GPU Acceleration (Experimental)")
        self.use_gpu_checkbox.setChecked(False) 
        self.use_gpu_checkbox.setToolTip("Uses Vector-based GPU acceleration (Taichi) for NFP calculation. Requires 'taichi' library.")
        gpu_layout.addWidget(self.use_gpu_checkbox)
        
        self.install_taichi_button = QtGui.QPushButton("Install Dependencies")
        self.install_taichi_button.setToolTip("Installs 'taichi' library to the current Python environment.")
        self.install_taichi_button.setMaximumWidth(100)
        gpu_layout.addWidget(self.install_taichi_button)
        
        minkowski_form_layout.addRow(gpu_layout)
        
        # Genetic options for Minkowski
        self.minkowski_population_size_input = QtGui.QSpinBox()
        self.minkowski_population_size_input.setRange(1, 500)
        self.minkowski_population_size_input.setValue(1)
        self.minkowski_population_size_input.setToolTip("Set to 1 for a single pass. Increase with generations for Genetic Algorithm.")
        
        self.minkowski_generations_input = QtGui.QSpinBox()
        self.minkowski_generations_input.setRange(1, 1000)
        self.minkowski_generations_input.setValue(1) # Default to 1 (No Genetic Loop)
        self.minkowski_generations_input.setToolTip("Set to 1 for a single pass. Increase to optimize using Genetic Algorithm.")

        # Rotation Steps for Minkowski
        self.minkowski_rotation_steps_slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.minkowski_rotation_steps_slider.setRange(0, len(self.rotation_angles) - 1)
        self.minkowski_rotation_steps_slider.setValue(3) # Default 90 deg
        self.minkowski_rotation_display_label = QtGui.QLabel("")
        self.minkowski_rotation_display_label.setFixedWidth(100)
        self.minkowski_rotation_steps_slider.valueChanged.connect(lambda: self._update_rotation_label())

        mink_rot_layout = QtGui.QHBoxLayout()
        mink_rot_layout.addWidget(self.minkowski_rotation_steps_slider)
        mink_rot_layout.addWidget(self.minkowski_rotation_display_label)
        minkowski_form_layout.addRow("Rotation Angle:", mink_rot_layout)

        minkowski_form_layout.addRow(QtGui.QLabel("")) # Spacer
        minkowski_form_layout.addRow(QtGui.QLabel("--- Optimization ---"))
        minkowski_form_layout.addRow("Generations:", self.minkowski_generations_input)
        minkowski_form_layout.addRow("Population Size:", self.minkowski_population_size_input)
        
        self.minkowski_settings_group.setLayout(minkowski_form_layout)

        # --- Physics Packer Settings ---
        self.physics_settings_group = QtGui.QGroupBox("Physics Nesting Settings")
        physics_form_layout = QtGui.QFormLayout()

        # Direction Dial for Physics
        self.physics_direction_dial = QtGui.QDial()
        self.physics_direction_dial.setRange(0, _MINKOWSKI_DIR_MAX)
        self.physics_direction_dial.setValue(0) 
        self.physics_direction_dial.setWrapping(True)
        self.physics_direction_dial.setNotchesVisible(True)
        self.physics_direction_label = QtGui.QLabel("Down")
        self.physics_direction_label.setAlignment(QtCore.Qt.AlignCenter)

        def update_physics_dial_label(value):
            direction_map = {0: "Down", 90: "Left", 180: "Up", 270: "Right"}
            direction_text = direction_map.get(value, "")
            self.physics_direction_label.setText(direction_text if direction_text else f"{value}°")
        self.physics_direction_dial.valueChanged.connect(update_physics_dial_label)

        physics_dial_layout = QtGui.QVBoxLayout()
        physics_dial_layout.addWidget(self.physics_direction_dial)
        physics_dial_layout.addWidget(self.physics_direction_label)

        self.physics_random_checkbox = QtGui.QCheckBox("Use Random Direction")
        self.physics_random_checkbox.stateChanged.connect(lambda state: self.physics_direction_dial.setDisabled(state))

        self.physics_step_size_input = QtGui.QDoubleSpinBox(); self.physics_step_size_input.setRange(0.1, 100); self.physics_step_size_input.setValue(5.0)
        self.physics_max_spawn_input = QtGui.QSpinBox(); self.physics_max_spawn_input.setRange(1, 1000); self.physics_max_spawn_input.setValue(100)
        self.physics_max_nesting_steps_input = QtGui.QSpinBox(); self.physics_max_nesting_steps_input.setRange(1, 5000); self.physics_max_nesting_steps_input.setValue(500)
        
        # Annealing controls
        self.physics_anneal_steps_input = QtGui.QSpinBox(); self.physics_anneal_steps_input.setRange(0, 500); self.physics_anneal_steps_input.setValue(25)
        self.anneal_rotate_checkbox = QtGui.QCheckBox("Anneal Rotate"); self.anneal_rotate_checkbox.setChecked(True)
        self.anneal_translate_checkbox = QtGui.QCheckBox("Anneal Translate"); self.anneal_translate_checkbox.setChecked(True)
        self.anneal_random_shake_checkbox = QtGui.QCheckBox("Random Shake Direction")

        self.physics_anneal_rot_steps = QtGui.QSpinBox(); self.physics_anneal_rot_steps.setRange(0, 500); self.physics_anneal_rot_steps.setValue(10)
        self.physics_anneal_rot_curve_type = QtGui.QComboBox()
        self.physics_anneal_rot_curve_type.addItems(["Logarithmic", "Linear", "Power 1.5", "Quadratic", "Exponential"])
        self.physics_anneal_rot_min = QtGui.QDoubleSpinBox(); self.physics_anneal_rot_min.setRange(0.0, 360.0); self.physics_anneal_rot_min.setValue(1.0)
        self.physics_anneal_rot_max = QtGui.QDoubleSpinBox(); self.physics_anneal_rot_max.setRange(0.0, 360.0); self.physics_anneal_rot_max.setValue(90.0)
        
        self.physics_anneal_curve_type = QtGui.QComboBox()
        self.physics_anneal_curve_type.addItems(["Logarithmic", "Linear", "Power 1.5", "Quadratic", "Exponential"])
        
        self.physics_anneal_min_amp = QtGui.QDoubleSpinBox(); self.physics_anneal_min_amp.setRange(0.0, 1000.0); self.physics_anneal_min_amp.setValue(0.1)
        self.physics_anneal_max_amp = QtGui.QDoubleSpinBox(); self.physics_anneal_max_amp.setRange(0.0, 5000.0); self.physics_anneal_max_amp.setValue(100.0)
        
        self.physics_improvement_threshold_input = QtGui.QDoubleSpinBox()
        self.physics_improvement_threshold_input.setRange(0.000001, 1.0)
        self.physics_improvement_threshold_input.setValue(0.01)
        self.physics_improvement_threshold_input.setSingleStep(0.01)
        self.physics_improvement_threshold_input.setDecimals(6)
        self.physics_improvement_threshold_input.setToolTip("Minimum score improvement required to reset simulation cycle. Prevents infinite loops from noise.")

        physics_form_layout.addRow("Gravity Direction:", physics_dial_layout)
        physics_form_layout.addRow(self.physics_random_checkbox)
        
        # Rotation Steps for Physics
        # Mapping: 1, 4 (90), 8 (45), 12 (30), 24 (15), 36 (10), 72 (5), 180 (2), 360 (1)
        self.physics_rotation_steps_slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.physics_rotation_steps_slider.setRange(0, 8) 
        self.physics_rotation_steps_slider.setValue(1) # Default 90 deg (4 steps)
        self.physics_rotation_display_label = QtGui.QLabel("")
        self.physics_rotation_display_label.setFixedWidth(120)
        self.physics_rotation_steps_slider.valueChanged.connect(lambda: self._update_rotation_label())

        physics_form_layout.addRow("Step Size:", self.physics_step_size_input)
        physics_form_layout.addRow("Max Spawn Attempts:", self.physics_max_spawn_input)
        physics_form_layout.addRow("Max Nesting Steps:", self.physics_max_nesting_steps_input)

        physics_form_layout.addRow(QtGui.QLabel("")) # Spacer
        physics_form_layout.addRow(QtGui.QLabel("--- Annealing (Shake) ---"))
        
        # Anneal Rotate Logic
        physics_form_layout.addRow(self.anneal_rotate_checkbox)
        phys_rot_layout = QtGui.QHBoxLayout()
        phys_rot_layout.addWidget(self.physics_rotation_steps_slider)
        phys_rot_layout.addWidget(self.physics_rotation_display_label)
        physics_form_layout.addRow("Rotation Steps:", phys_rot_layout)
        physics_form_layout.addRow("Rot Anneal Steps:", self.physics_anneal_rot_steps)
        physics_form_layout.addRow("Rot Curve Type:", self.physics_anneal_rot_curve_type)
        physics_form_layout.addRow("Rot Min Angle:", self.physics_anneal_rot_min)
        physics_form_layout.addRow("Rot Max Angle:", self.physics_anneal_rot_max)
        
        # Anneal Translate Logic
        physics_form_layout.addRow(self.anneal_translate_checkbox)
        physics_form_layout.addRow("Anneal Steps:", self.physics_anneal_steps_input)
        physics_form_layout.addRow("Improvement Threshold:", self.physics_improvement_threshold_input)
        physics_form_layout.addRow(QtGui.QLabel("")) # Spacer
        physics_form_layout.addRow("Curve Type:", self.physics_anneal_curve_type)
        physics_form_layout.addRow("Min Amplitude:", self.physics_anneal_min_amp)
        physics_form_layout.addRow("Max Amplitude:", self.physics_anneal_max_amp)
        physics_form_layout.addRow(self.anneal_random_shake_checkbox)

        self.physics_settings_group.setLayout(physics_form_layout)

        # Set initial visibility
        self.minkowski_settings_group.setVisible(True)
        self.physics_settings_group.setVisible(False)





        self.show_bounds_checkbox = QtGui.QCheckBox("Show Bounds"); self.show_bounds_checkbox.setChecked(True)
        self.add_labels_checkbox = QtGui.QCheckBox("Add Identifier Labels"); self.add_labels_checkbox.setChecked(True)
        self.label_height_input = QtGui.QDoubleSpinBox(); self.label_height_input.setRange(0, 1000); self.label_height_input.setValue(25.0)
        self.label_height_input.setToolTip("The height (Z-offset) for the identifier labels.")
        self.label_size_input = QtGui.QDoubleSpinBox(); self.label_size_input.setRange(1, 100); self.label_size_input.setValue(10.0)
        self.label_size_input.setToolTip("The text size for identifier labels in mm.")
        self.simulate_nesting_checkbox = QtGui.QCheckBox("Simulate Nesting (slower)"); self.simulate_nesting_checkbox.setChecked(True)
        self.verbose_logging_checkbox = QtGui.QCheckBox("Verbose Logging"); self.verbose_logging_checkbox.setChecked(_DEFAULTS["verbose_logging"])
        self.verbose_logging_checkbox.setToolTip("Enables detailed logging of the nesting process in the FreeCAD console.")
        self.sound_checkbox = QtGui.QCheckBox("Play sound on completion"); self.sound_checkbox.setChecked(True)
        
        self.nest_button = QtGui.QPushButton("Run Nesting")
        self.cancel_button = QtGui.QPushButton("Cancel Nesting")
        self.cancel_button.setEnabled(False)

        # --- Add/Remove buttons for the shape table ---
        self.add_parts_button = QtGui.QPushButton("Add Selected")
        self.remove_parts_button = QtGui.QPushButton("Remove Selected")
        
        # --- Font Selection UI Elements ---
        self.font_select_button = QtGui.QPushButton("Select Font")
        self.font_label = QtGui.QLabel("No Font Selected")
        self.font_label.setWordWrap(True)
        font_layout.addWidget(self.font_select_button)
        font_layout.addWidget(self.font_label)
        
        self.status_label = QtGui.QLabel("Select master shapes to nest.")
        self.status_label.setWordWrap(True)

        # --- Layout Assembly ---
        label_options_layout = QtGui.QHBoxLayout()
        label_options_layout.addWidget(self.add_labels_checkbox)
        label_options_layout.addWidget(QtGui.QLabel("Size:"))
        label_options_layout.addWidget(self.label_size_input)
        label_options_layout.addWidget(QtGui.QLabel("Height (Z):"))
        label_options_layout.addWidget(self.label_height_input)
        label_options_layout.addStretch()


        form_layout.addRow("Sheet Width:", self.sheet_width_input)
        form_layout.addRow("Sheet Height:", self.sheet_height_input)
        form_layout.addRow("Sheet Thickness:", self.sheet_thickness_input)
        form_layout.addRow("Part Spacing:", self.part_spacing_input)
        
        # Advanced Curve Settings
        curve_settings_layout = QtGui.QHBoxLayout()
        curve_settings_layout.addWidget(QtGui.QLabel("Curve:"))
        curve_settings_layout.addWidget(self.deflection_input)
        curve_settings_layout.addWidget(QtGui.QLabel("Simplify:"))
        curve_settings_layout.addWidget(self.simplification_input)
        
        form_layout.addRow("Bounds Resolution:", curve_settings_layout)


        form_layout.addRow(self.minkowski_settings_group)
        form_layout.addRow(self.physics_settings_group)

        form_layout.addRow("Identifier Font:", font_layout)
        form_layout.addRow(label_options_layout)
        

        form_layout.addRow(self.simulate_nesting_checkbox)
        form_layout.addRow(self.verbose_logging_checkbox)
        form_layout.addRow(self.show_bounds_checkbox) # Keep this on its own line
        form_layout.addRow(self.sound_checkbox)
        
        table_button_layout.addWidget(self.add_parts_button)
        table_button_layout.addWidget(self.remove_parts_button)

        action_button_layout.addWidget(self.nest_button)
        action_button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.shape_table)
        main_layout.addLayout(table_button_layout)
        main_layout.addLayout(action_button_layout)
        
        # --- Progress Bar ---
        self.progressBar = QtGui.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(True)
        self.progressBar.setVisible(False) # Hidden by default
        main_layout.addWidget(self.progressBar)

        main_layout.addWidget(self.status_label)
        main_layout.addStretch()
        
        self.setLayout(main_layout)

        # Connect signals


        # Link label inputs to the add labels checkbox
        def toggle_label_inputs(state):
            enabled = state == QtCore.Qt.Checked
            self.label_size_input.setEnabled(enabled)
            self.label_height_input.setEnabled(enabled)
        
        self.add_labels_checkbox.stateChanged.connect(toggle_label_inputs)
        toggle_label_inputs(QtCore.Qt.Checked if self.add_labels_checkbox.isChecked() else QtCore.Qt.Unchecked)

        # Connect the nesting controller
        from .nesting_controller import NestingController
        self.controller = NestingController(self)
        self.nest_button.clicked.connect(self.controller.execute_nesting)
        self.cancel_button.clicked.connect(self.controller.request_cancel)
        self.font_select_button.clicked.connect(self.select_font_file)
        self.show_bounds_checkbox.stateChanged.connect(self.controller.toggle_bounds_visibility)
        self.add_parts_button.clicked.connect(self.controller.add_selected_shapes)
        self.remove_parts_button.clicked.connect(self.controller.remove_selected_shapes)
        
        # Connect Taichi install button
        if hasattr(self, 'install_taichi_button'):
            self.install_taichi_button.clicked.connect(self.controller.install_taichi)
            # Check availability to disable/enable
            try:
                import taichi
                self.install_taichi_button.setEnabled(False)
                self.install_taichi_button.setText("Dependencies Installed")
            except ImportError:
                self.install_taichi_button.setEnabled(True)
        
        self.load_persisted_settings()
        
        # Ensure initial labels are correct
        self._update_rotation_label()
        
        # Load initial selection
        self.controller.load_selection()

    def add_part_row(self, row_index, label, quantity=1, rotation_steps=4, override_rotation=False, 
                       up_direction="Z+", fill_sheet=False):
        """Helper function to create and populate a single row in the parts table."""
        label_item = QtGui.QTableWidgetItem(label)
        label_item.setFlags(label_item.flags() & ~QtCore.Qt.ItemIsEditable)

        quantity_spinbox = QtGui.QSpinBox()
        quantity_spinbox.setRange(1, 500)
        quantity_spinbox.setValue(quantity)

        # --- Rotation Override Widget ---
        rotation_widget = QtGui.QWidget()
        rotation_layout = QtGui.QHBoxLayout(rotation_widget)
        rotation_layout.setContentsMargins(0, 0, 0, 0)
        
        rotation_slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        rotation_slider.setRange(0, 360) # Allow 0 for no rotation
        rotation_slider.setValue(rotation_steps)
        
        rotation_spinbox = QtGui.QSpinBox()
        rotation_spinbox.setRange(0, 360) # Allow 0 for no rotation
        rotation_spinbox.setValue(rotation_steps)
        rotation_spinbox.setToolTip("Override global rotation steps for this part. 0 or 1 means no rotation.")

        rotation_slider.valueChanged.connect(rotation_spinbox.setValue)
        rotation_spinbox.valueChanged.connect(rotation_slider.setValue)
        
        rotation_layout.addWidget(rotation_slider)
        rotation_layout.addWidget(rotation_spinbox)

        override_checkbox = QtGui.QCheckBox()
        override_checkbox.setChecked(override_rotation)
        override_checkbox.stateChanged.connect(rotation_widget.setEnabled)
        rotation_widget.setEnabled(override_rotation) # Disabled by default unless overridden

        # --- Up Direction Combo ---
        up_dir_combo = QtGui.QComboBox()
        up_dir_combo.addItems(["Z+", "Z-", "Y+", "Y-", "X+", "X-"])
        up_dir_combo.setCurrentText(up_direction)
        up_dir_combo.setToolTip("Define which direction is 'up' for this part when projecting to 2D.")

        # --- Fill Sheet Checkbox ---
        fill_checkbox = QtGui.QCheckBox()
        fill_checkbox.setChecked(fill_sheet)
        fill_checkbox.setToolTip("If checked, this part will be used to fill remaining space after all other parts are placed.")

        self.shape_table.setItem(row_index, 0, label_item)
        self.shape_table.setCellWidget(row_index, 1, quantity_spinbox)
        self.shape_table.setCellWidget(row_index, 2, rotation_widget)
        self.shape_table.setCellWidget(row_index, 3, override_checkbox)
        self.shape_table.setCellWidget(row_index, 4, up_dir_combo)
        self.shape_table.setCellWidget(row_index, 5, fill_checkbox)

    def select_font_file(self):
        """Opens a file dialog to let the user select a font file."""
        # Correctly find the workbench's root directory and the 'fonts' subfolder
        try:
            # __file__ is the path to this file (ui_nesting.py)
            # os.path.dirname gives the directory it's in (.../nesting)
            # We need to go up three levels from .../Tools/Nesting/ to get to the workbench root.
            current_dir = os.path.dirname(os.path.abspath(__file__))
            workbench_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
            default_font_dir = os.path.join(workbench_root, "fonts")
            if not os.path.isdir(default_font_dir):
                default_font_dir = "" # Fallback if fonts dir doesn't exist
        except Exception:
            default_font_dir = "" # Fallback on any error

        file_dialog_result = QtGui.QFileDialog.getOpenFileName(
            self, 
            "Select Font File", 
            default_font_dir, # Set the default directory
            "Font Files (*.ttf *.otf)"
        )
        font_path = file_dialog_result[0]

        if font_path:
            self.selected_font_path = font_path
            # Display just the filename for a cleaner UI
            self.font_label.setText(os.path.basename(font_path))

    def set_default_font(self):
        """Checks for and sets a default font on initialization."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            workbench_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
            fonts_dir = os.path.join(workbench_root, "fonts")
            default_font_file = "PoiretOne-Regular.ttf"
            default_font_path = os.path.join(fonts_dir, default_font_file)

            if os.path.exists(default_font_path):
                self.selected_font_path = default_font_path
                self.font_label.setText(default_font_file)
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[NestingPanel] Failed to set default font: {e}\n")

    def log_message(self, message, level="message"):
        """Displays a message in the status label and logs to the console."""
        try:
            self.status_label.setText(message)
        except RuntimeError:
            # The widget C++ object has been deleted (panel closed), but Python object persists.
            # We can just log to console and ignore the UI update.
            pass

        if level == "warning":
            FreeCAD.Console.PrintWarning(message + "\n")
        else:
            FreeCAD.Console.PrintMessage(message + "\n")
        
        # Process UI events to make sure the label updates immediately
        # We wrap this too, just in case
        try:
            FreeCADGui.updateGui()
        except RuntimeError:
            pass

    def load_persisted_settings(self):
        """Loads settings from FreeCAD preferences."""
        prefs = FreeCAD.ParamGet(PREFS_PATH)
        self.sheet_width_input.setValue(prefs.GetFloat(PROP_SHEET_WIDTH, 600.0))
        self.sheet_height_input.setValue(prefs.GetFloat(PROP_SHEET_HEIGHT, 600.0))
        self.part_spacing_input.setValue(prefs.GetFloat(PROP_PART_SPACING, 12.5))
        self.sheet_thickness_input.setValue(prefs.GetFloat(PROP_SHEET_THICKNESS, 3.0))
        self.label_size_input.setValue(prefs.GetFloat(PROP_LABEL_SIZE, 10.0))
        # Load deflection angle (new format) or use default of 30°
        deflection_angle = prefs.GetFloat(PROP_DEFLECTION_ANGLE, 0)
        if deflection_angle == 0:
            # Backward compatibility: convert old Deflection (mm) to angle, or use 30° default
            old_deflection = prefs.GetFloat("Deflection", 0)
            if old_deflection > 0:
                deflection_angle = old_deflection * 200.0  # Inverse of mm = angle/200
            else:
                deflection_angle = 30  # Default
        self.deflection_input.setValue(deflection_angle)
        self.simplification_input.setValue(prefs.GetFloat(PROP_SIMPLIFICATION, 1.0))
        self.use_gpu_checkbox.setChecked(prefs.GetBool(PROP_USE_GPU, False))
        self.verbose_logging_checkbox.setChecked(prefs.GetBool("VerboseLogging", False))
        self.physics_improvement_threshold_input.setValue(prefs.GetFloat("PhysicsStabilityTolerance", 0.01))
        
        self.physics_anneal_curve_type.setCurrentText(prefs.GetString("PhysicsAnnealCurveType", "Logarithmic"))
        self.physics_anneal_min_amp.setValue(prefs.GetFloat("PhysicsAnnealMinAmp", 0.1))
        self.physics_anneal_max_amp.setValue(prefs.GetFloat("PhysicsAnnealMaxAmp", 100.0))
        
        self.physics_anneal_rot_steps.setValue(prefs.GetInt("PhysicsAnnealRotSteps", 10))
        self.physics_anneal_rot_curve_type.setCurrentText(prefs.GetString("PhysicsAnnealRotCurveType", "Logarithmic"))
        self.physics_anneal_rot_min.setValue(prefs.GetFloat("PhysicsAnnealRotMin", 1.0))
        self.physics_anneal_rot_max.setValue(prefs.GetFloat("PhysicsAnnealRotMax", 90.0))
        
        # Load Rotation Steps (Isolated)
        # Minkowski
        mink_rot_steps = prefs.GetInt("MinkowskiRotationSteps", 4) # Default 90 deg (4 steps)
        if mink_rot_steps > 0:
            target_angle = 360.0 / mink_rot_steps
            closest_idx = 0
            min_diff = float('inf')
            for i, angle in enumerate(self.rotation_angles):
                diff = abs(angle - target_angle)
                if diff < min_diff:
                    min_diff = diff
                    closest_idx = i
            self.minkowski_rotation_steps_slider.setValue(closest_idx)
            
        # Physics
        phys_rot_steps = prefs.GetInt("PhysicsRotationSteps", 4) # Default 90 deg (4 steps)
        if phys_rot_steps > 0:
            target_angle = 360.0 / phys_rot_steps
            phys_angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]
            closest_idx = 0
            min_diff = float('inf')
            for i, angle in enumerate(phys_angles):
                diff = abs(angle - target_angle)
                if diff < min_diff:
                    min_diff = diff
                    closest_idx = i
            self.physics_rotation_steps_slider.setValue(closest_idx)
        
    def update_progress(self, current, total, message=None):
        """Updates the progress bar."""
        try:
            if total > 0:
                percentage = int((float(current) / float(total)) * 100)
                self.progressBar.setValue(percentage)
                self.progressBar.setVisible(True)
                
                if message:
                    self.progressBar.setFormat(f"%p% - {message}")
                else:
                    self.progressBar.setFormat("%p%")
                
                # Force UI update
                FreeCADGui.updateGui()
            else:
                self.progressBar.setValue(0)
                self.progressBar.setVisible(False)
        except RuntimeError:
            pass # Widget deleted
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"UI Update Error: {e}\n")

    def _update_rotation_label(self):
        algo = self.algorithm_dropdown.currentText()
        
        if algo == "Physics":
            value = self.physics_rotation_steps_slider.value()
            angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]
            if value < len(angles):
                angle = angles[value]
                steps = int(360 / angle) if angle > 0 else 1
                self.physics_rotation_display_label.setText(f"{angle}° ({steps} steps)")
        else:
            value = self.minkowski_rotation_steps_slider.value()
            angles = self.rotation_angles
            if value < len(angles):
                angle = angles[value]
                self.minkowski_rotation_display_label.setText(f"{angle}°")

    def _on_algorithm_change(self, algo_name):
        """Handles switching between nesting algorithms."""
        self.minkowski_settings_group.setVisible(algo_name == "Minkowski")
        self.physics_settings_group.setVisible(algo_name == "Physics")
        # Ensure the rotation label/steps are immediately clarified for the new algorithm
        self._update_rotation_label()

    def reset_progress(self):
        """Resets and hides the progress bar."""
        try:
            self.progressBar.setValue(0)
            self.progressBar.setVisible(False)
        except RuntimeError: pass
        
