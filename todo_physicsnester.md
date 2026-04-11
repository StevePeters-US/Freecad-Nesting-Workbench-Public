### TASK-001: Implement Physics Nester

| Field       | Value                |
|-------------|----------------------|
| Complexity  | Medium               |
| Component   | `nestingworkbench/Tools/Nesting/` |
| Depends on  | None                 |

**Context** — Re-implementing the previously removed "Gravity Nester" as the "Physics Nester" and evaluating it alongside the unified Minkowski/Genetic nester.

#### T-001: Create physics_nester.py
- [ ] **T-001** `nestingworkbench/Tools/Nesting/algorithms/physics_nester.py` (NEW FILE)
  Create the new algorithm file. Copy the implementation from `.agents/skills/nw_physics_nester/SKILL.md`. Ensure it inherits from the appropriate base nester.

#### T-002: Update nesting_logic.py
- [ ] **T-002** `nestingworkbench/Tools/Nesting/nesting_logic.py`
  Modify `nest(parts, width, height, ...)` to accept an `algorithm` parameter (or accept it via kwargs).
  ```python
  from .algorithms import physics_nester
  from .algorithms import nesting_strategy

  def nest(parts, width, height, rotation_steps=1, simulate=False, algorithm='Minkowski', **kwargs):
      # ... (existing setup code)
      
      if algorithm == 'Physics':
          nester = physics_nester.PhysicsNester(width, height, rotation_steps, **kwargs)
      else:
          # Default to the existing Minkowski/Genetic strategy
          nester = nesting_strategy.Nester(width, height, rotation_steps, **kwargs)
  ```

#### T-003: Update ui_nesting.py for Algorithm Selection
- [ ] **T-003** `nestingworkbench/Tools/Nesting/ui_nesting.py`
  Add a dropdown to select between the default Minkowski layout and the new Physics nester, and default it to Physics. Add a group for the Physics settings, utilizing the variables from the `SKILL.md` reference.
  Create `self.physics_settings_group` alongside `self.minkowski_settings_group`.
  Add `self.algorithm_dropdown = QtGui.QComboBox()` with `["Minkowski", "Physics"]` and `setCurrentIndex(1)`.
  Connect visibility of the groups (`minkowski_settings_group`, `physics_settings_group`) to changes in this new dropdown.

#### T-004: Map Settings in nesting_controller.py
- [ ] **T-004** `nestingworkbench/Tools/Nesting/nesting_controller.py` inside `_prepare_algo_kwargs` and `get_ui_params`
  In `get_ui_params(self)`, extract the `algorithm` chosen from `self.ui.algorithm_dropdown.currentText()`.
  In `_prepare_algo_kwargs(self, ui_params)`, branch the logic based on the algorithm:
  ```python
      def _prepare_algo_kwargs(self, ui_params):
          algo_kwargs = {}
          algorithm = ui_params.get('algorithm', 'Minkowski')
          
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
          else:
              # Keep all existing Minkowski kwargs mappings intact
              pass
              
          return algo_kwargs
  ```
  Ensure that `algorithm` is properly passed down from the controller's `run()` to `nesting_logic.nest()`.

**Acceptance criteria**

1. The "Physics Nester Settings" group is dynamically swapped with the "Minkowski Nesting Settings" group when toggling the dropdown.
2. The "Physics" algorithm is selected by default upon opening the Nesting Panel.
3. Nesting with the "Physics" algorithm successfully uses logic from `physics_nester.py` and passes the unique physics parameters.
