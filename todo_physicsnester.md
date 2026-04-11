### TASK-001: Implement Physics Nester

| Field       | Value                |
|-------------|----------------------|
| Complexity  | Medium               |
| Component   | `nestingworkbench/Tools/Nesting/` |
| Depends on  | None                 |

**Context** — Re-implementing the previously removed "Gravity Nester" as the "Physics Nester" and making it the default algorithm for the nesting workbench.

#### T-001: Create physics_nester.py
- [ ] **T-001** `nestingworkbench/Tools/Nesting/algorithms/physics_nester.py` (NEW FILE)
  Create the new algorithm file. Copy the implementation from `.agents/skills/nw_physics_nester/SKILL.md`.

#### T-002: Update nesting_logic.py mappings
- [ ] **T-002** `nestingworkbench/Tools/Nesting/nesting_logic.py` lines 6-10 and 35-43
  Import `PhysicsNester` and register it.
  ```python
  from .algorithms import (
      genetic_nester,
      physics_nester,
      minkowski_nester)
  ```
  ```python
      nester_class = {
          'Genetic': genetic_nester.GeneticNester,
          'Minkowski': minkowski_nester.MinkowskiNester,
          'Physics': physics_nester.PhysicsNester,
      }.get(algorithm)

      if nester_class is None:
          raise NotImplementedError(f"The algorithm '{algorithm}' is not supported.")

      SHAPELY_ALGORITHMS = ['Genetic', 'Minkowski', 'Physics']
  ```

#### T-003: Update ui_nesting.py for Algorithm Selection
- [ ] **T-003** `nestingworkbench/Tools/Nesting/ui_nesting.py` lines 56-57 and around line 105
  Add "Physics" to the algorithm dropdown, make it the default, and add its settings UI group.
  ```python
          self.algorithm_dropdown = QtGui.QComboBox()
          self.algorithm_dropdown.addItems(["Genetic", "Minkowski", "Physics"])
          self.algorithm_dropdown.setCurrentIndex(2)
  ```
  Add the UI widgets block for `self.physics_settings_group` as defined in `.agents/skills/nw_physics_nester/SKILL.md`. Add this around line 105 where the old `gravity_settings_group` was removed.
  Make sure to also map the visibility toggle around line 197 in `on_algorithm_change`: `self.physics_settings_group.setVisible(algo_name == "Physics")` and add it to `form_layout.addRow(self.physics_settings_group)` around line 148.

#### T-004: Map Settings in nesting_controller.py
- [ ] **T-004** `nestingworkbench/Tools/Nesting/nesting_controller.py` lines 884-900 (`_prepare_algo_kwargs`)
  Extract UI values for the Physics nester if selected.
  ```python
      def _prepare_algo_kwargs(self, ui_params):
          algo_kwargs = {}
          algorithm = ui_params['algorithm']
          
          if algorithm == 'Physics':
              if self.ui.physics_random_checkbox.isChecked():
                  algo_kwargs['physics_direction'] = None 
              else:
                  angle_deg = (270 - self.ui.physics_direction_dial.value()) % 360
                  angle_rad = math.radians(angle_deg)
                  algo_kwargs['physics_direction'] = (math.cos(angle_rad), math.sin(angle_rad))
              algo_kwargs['step_size'] = self.ui.physics_step_size_input.value()
              algo_kwargs['anneal_rotate_enabled'] = self.ui.anneal_rotate_checkbox.isChecked()
              algo_kwargs['anneal_translate_enabled'] = self.ui.anneal_translate_checkbox.isChecked()
              algo_kwargs['anneal_random_shake_direction'] = self.ui.anneal_random_shake_checkbox.isChecked()
              algo_kwargs['max_spawn_count'] = self.ui.physics_max_spawn_input.value()
              algo_kwargs['anneal_steps'] = self.ui.physics_anneal_steps_input.value()
              algo_kwargs['max_nesting_steps'] = self.ui.physics_max_nesting_steps_input.value()
  ```

**Acceptance criteria**

1. The "Physics Nester Settings" group is visible in the UI when the "Physics" algorithm is selected.
2. The "Physics" algorithm is selected by default upon opening the Nesting Panel.
3. Nesting with the "Physics" algorithm successfully places parts on the sheet using the simulated physics direction.
