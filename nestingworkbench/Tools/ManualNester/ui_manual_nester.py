# Nesting/nestingworkbench/Tools/ManualNester/ui_manual_nester.py

"""
This module contains the ManualNesterToolUI class, which defines the user interface
for the manual nester tool task panel.
"""

from PySide import QtGui, QtCore

class ManualNesterToolUI(QtGui.QWidget):
    """
    Defines the user interface for the manual nester tool task panel.
    """
    def __init__(self, parent=None):
        super(ManualNesterToolUI, self).__init__(parent)
        self.setWindowTitle("Manual Nester")
        self.initUI()

    def initUI(self):
        main_layout = QtGui.QVBoxLayout()

        info_label = QtGui.QLabel("Click and drag parts in the 3D view to move them.\n\nUse the 'OK' button to save changes or 'Cancel' to revert.")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        # Mode Group
        mode_group = QtGui.QGroupBox("Mode")
        mode_layout = QtGui.QVBoxLayout()

        self.radio_physics = QtGui.QRadioButton("Push parts (Physics)")
        self.radio_physics.setToolTip("Dragging a part pushes nearby parts out of the way.")
        self.radio_physics.setChecked(True)

        self.radio_valid = QtGui.QRadioButton("Valid placement only")
        self.radio_valid.setToolTip("The dragged part only moves to positions that don't overlap other parts.")

        self.radio_autorotate = QtGui.QRadioButton("Auto-rotate to fit")
        self.radio_autorotate.setToolTip("Pushes nearby parts and also rotates the dragged part for tighter fitment.")

        mode_layout.addWidget(self.radio_physics)
        mode_layout.addWidget(self.radio_valid)
        mode_layout.addWidget(self.radio_autorotate)
        mode_group.setLayout(mode_layout)
        main_layout.addWidget(mode_group)

        # Physics Settings Group (advanced controls)
        self.physics_group = QtGui.QGroupBox("Physics Settings")
        physics_layout = QtGui.QVBoxLayout()

        radius_layout = QtGui.QHBoxLayout()
        radius_layout.addWidget(QtGui.QLabel("Influence Radius (mm):"))
        self.radius_spin = QtGui.QDoubleSpinBox()
        self.radius_spin.setRange(0, 1000)
        self.radius_spin.setValue(200)
        self.radius_spin.setSingleStep(10)
        radius_layout.addWidget(self.radius_spin)
        physics_layout.addLayout(radius_layout)

        curve_layout = QtGui.QHBoxLayout()
        curve_layout.addWidget(QtGui.QLabel("Falloff Curve:"))
        self.curve_dropdown = QtGui.QComboBox()
        self.curve_dropdown.addItems(["Linear", "Smooth", "Sharp"])
        self.curve_dropdown.setCurrentIndex(1)
        curve_layout.addWidget(self.curve_dropdown)
        physics_layout.addLayout(curve_layout)

        strength_layout = QtGui.QHBoxLayout()
        strength_layout.addWidget(QtGui.QLabel("Strength:"))
        self.strength_spin = QtGui.QDoubleSpinBox()
        self.strength_spin.setRange(0.1, 2.0)
        self.strength_spin.setValue(1.0)
        self.strength_spin.setSingleStep(0.1)
        strength_layout.addWidget(self.strength_spin)
        physics_layout.addLayout(strength_layout)

        self.physics_group.setLayout(physics_layout)
        main_layout.addWidget(self.physics_group)

        main_layout.addStretch()
        self.setLayout(main_layout)

        # Grey out physics settings when valid-placement mode is active
        self.radio_valid.toggled.connect(
            lambda checked: self.physics_group.setEnabled(not checked)
        )
