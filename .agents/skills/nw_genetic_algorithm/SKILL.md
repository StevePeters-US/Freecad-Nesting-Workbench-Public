# Skill: Genetic Algorithm

> Read this before modifying the GA loop, fitness function, crossover, or mutation.

## Files to Read First

- `nestingworkbench/Tools/Nesting/layout_manager.py` — `Layout`, `LayoutManager`, fitness
- `nestingworkbench/Tools/Nesting/algorithms/genetic_utils.py` — GA operators
- `nestingworkbench/Tools/Nesting/nesting_controller.py` — `_execute_ga_nesting()` loop

## GA Architecture

### Chromosome
A list of `(part_id, rotation_angle)` tuples. Encodes the order in which parts are placed and at what angle.

### Fitness Function
```
fitness = sheets * sheet_area + last_sheet_bbox - contact_bonus
```
Lower = better. See `Layout.calculate_efficiency()` in `layout_manager.py`.

### GA Loop (in `_execute_ga_nesting()`)
1. Create N layouts with shuffled orderings
2. Nest each layout independently
3. Sort by fitness
4. Delete worst layouts
5. Repeat for G generations

### Known Issues (TASK-007, TASK-008)
- Fitness function uses raw values that vary wildly with part count/scale
- `ordered_crossover()` and `tournament_selection()` exist but are **never called** (dead code)
- Each generation creates brand-new layouts from scratch, discarding genetic info
- All layouts in a generation use the same packing direction
- No proper seeding for reproducibility

## Key APIs

| Symbol | Location | Purpose |
|--------|----------|---------|
| `LayoutManager.create_ga_population()` | `layout_manager.py` | Create N candidate layouts |
| `Layout.calculate_efficiency()` | `layout_manager.py` | Fitness function |
| `Layout._calculate_contact_score()` | `layout_manager.py` | Contact bonus (shared edges) |
| `ordered_crossover()` | `genetic_utils.py` | OX crossover operator |
| `mutate_chromosome()` | `genetic_utils.py` | Random swap mutation |
| `tournament_selection()` | `genetic_utils.py` | k-tournament parent selection |

## Gotchas

- The GA loop runs on the main thread (blocks UI) — see TASK-013
- `processEvents()` calls are fragile
- Contact score uses hardcoded 0.5mm buffer (should use part spacing)
- The GA has zero variation between runs with small part counts
