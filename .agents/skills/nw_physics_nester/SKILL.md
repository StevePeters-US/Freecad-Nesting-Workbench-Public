---
description: Reference code and guidelines for implementing the Physics Nester (formerly Gravity Nester).
---

# Skill: Physics Nester Re-implementation

> Read this before implementing any tasks from `todo_physicsnester.md`.

## Context
The Physics Nester is a re-implementation of the previously removed "Gravity Nester" (removed in commit `dca0e892`). It is being renamed to "Physics" nester to be more accurate, and must be set as the default algorithm.

## Changes Required

- **Algorithms**: Create `nestingworkbench/Tools/Nesting/algorithms/physics_nester.py`.
- **UI**: Add "Physics" to the algorithm dropdown in `ui_nesting.py`, set it as the default, and restore its specific settings group.
- **Logic**: Update `nesting_logic.py` and `nesting_controller.py` to map the new algorithm and its parameters.

## Reference Code (From removed `gravity_nester.py`)

Here is the original logic. You must port this to use "Physics" terminology instead of "Gravity":

```python
import random
import math
import FreeCAD
from .base_nester import BaseNester

class PhysicsNester(BaseNester):
    \"\"\"
    A packer that uses a simple physics simulation.
    Parts are spawned at a random location and then moved in a specified
    direction until they collide with the sheet edge or another part.
    \"\"\"

    def __init__(self, width, height, rotation_steps=1, **kwargs):
        super().__init__(width, height, rotation_steps, **kwargs)
        # --- Algorithm-specific parameters ---
        self.physics_direction = kwargs.get("physics_direction", (0, -1))
        self.max_spawn_count = kwargs.get("max_spawn_count", 100)
        self.max_nesting_steps = kwargs.get("max_nesting_steps", 500)

    def _spawn_part_on_sheet(self, shape, sheet):
        for _ in range(self.max_spawn_count):
            if shape.rotation_steps > 1:
                angle = random.randrange(shape.rotation_steps) * (360 / shape.rotation_steps)
                shape.set_rotation(angle)

            _, _, w, h = shape.bounding_box()
            
            max_target_x = self._bin_width - w
            max_target_y = self._bin_height - h
            target_x = random.uniform(0, max_target_x) if max_target_x > 0 else 0
            target_y = random.uniform(0, max_target_y) if max_target_y > 0 else 0
            shape.move_to(target_x, target_y)

            if sheet.is_placement_valid(shape):
                return shape
        return None

    def _try_place_part_on_sheet(self, part_to_place, sheet):
        spawned_part = self._spawn_part_on_sheet(part_to_place, sheet)
        
        if spawned_part:
            if self.physics_direction is None:
                angle_rad = random.uniform(0, 2 * math.pi)
                part_direction = (math.cos(angle_rad), math.sin(angle_rad))
            else:
                part_direction = self.physics_direction
            
            return self._move_until_collision(spawned_part, sheet, part_direction)
        else:
            return None

    def _apply_physics_to_part(self, part, sheet, direction):
        for _ in range(self.max_nesting_steps):
            dx = direction[0] * self.step_size
            dy = direction[1] * self.step_size

            part.move(dx, dy)

            if self.update_callback:
                self.update_callback(part, sheet)

            is_valid = sheet.is_placement_valid(part, part_to_ignore=part)
            if not is_valid:
                part.move(-dx, -dy)
                if self.update_callback:
                    self.update_callback(part, sheet)
                break

    def _move_until_collision(self, part, sheet, direction):
        cycle = 0
        while cycle < self.max_nesting_steps:
            cycle += 1

            pre_physics_x, pre_physics_y, _, _ = part.bounding_box()
            self._apply_physics_to_part(part, sheet, direction)
            post_physics_x, post_physics_y, _, _ = part.bounding_box()
            physics_moved = abs(post_physics_x - pre_physics_x) > 1e-6 or abs(post_physics_y - pre_physics_y) > 1e-6

            if physics_moved:
                continue

            pre_anneal_x, pre_anneal_y, _, _ = part.bounding_box()
            self._anneal_part(part, sheet, direction, rotate_enabled=self.anneal_rotate_enabled, translate_enabled=self.anneal_translate_enabled)
            post_anneal_x, post_anneal_y, _, _ = part.bounding_box()
            shake_moved = abs(post_anneal_x - pre_anneal_x) > 1e-6 or abs(post_anneal_y - pre_anneal_y) > 1e-6

            if shake_moved:
                continue

            break

        return part
```

## Controller Logic (From removed UI binding)
Remember to rename `gravity_` variables to `physics_` when porting to `nesting_controller.py`:
```python
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
