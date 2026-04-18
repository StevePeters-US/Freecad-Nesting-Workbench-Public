# Skill: Nesting Threading & Parallelism

> Read this before modifying nesting execution threading, QThread workers, or parallelism.

## Files to Read First

- `nestingworkbench/Tools/Nesting/nesting_controller.py` — orchestrator, runs nesting synchronously on main thread
- `nestingworkbench/Tools/Nesting/ga_coordinator.py` — GA loop, interleaves compute with FreeCAD doc ops
- `nestingworkbench/Tools/Nesting/algorithms/nesting_strategy.py` — `Nester`, `PlacementOptimizer` with ThreadPoolExecutor
- `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` — NFP computation, cache locking
- `nestingworkbench/Tools/Nesting/nesting_logic.py` — `nest()` entry, simulation callbacks
- `nestingworkbench/datatypes/shape.py` — `Shape.nfp_cache`, `Shape.nfp_cache_lock`

## Current Threading Architecture

### Main Thread Blocking Problem

The entire nesting pipeline runs synchronously on the FreeCAD main (GUI) thread:

```
NestingController.run()              [main thread, line 342]
  └─ _execute_ga_nesting()           [main thread, line 346]
       └─ GACoordinator.run()        [main thread, line 677]
            └─ _run_generation()     [main thread, line 110]
                 └─ nest()           [main thread]
                      └─ Nester._nest_standard()  [main thread, line 283]
                           └─ PlacementOptimizer.find_best_placement()  [main thread]
```

`FreeCADGui.updateGui()` is called between generations/layouts (ga_coordinator.py:88,108,227) but NOT during the inner NFP computation loop, so the GUI is frozen during the expensive part.

### Existing Parallelism (CPU Path)

1. **Rotation evaluation** — `ThreadPoolExecutor` at nesting_strategy.py:98-114
   - Submits `_evaluate_rotation()` for each rotation angle
   - Limited by Python GIL for CPU-bound Shapely work (though GEOS C calls release GIL)
   
2. **Background precomputation** — `ThreadPoolExecutor` pool at nesting_strategy.py:256
   - Fire-and-forget NFP computations for future parts
   - Only used in CPU mode (GPU mode skips, line 360)

3. **NFP cache lock** — `Shape.nfp_cache_lock` (shape.py:36)
   - Global threading.Lock, held for all cache reads/writes
   - Potential contention point with many threads

### Existing Parallelism (GPU Path)

1. **Batch NFP** — `precompute_nfp_batch()` (minkowski_engine.py:356-473)
   - Single Taichi kernel call processes all angle rotations at once
   
2. **GPU kernel lock** — `nfp_gpu_taichi._kernel_lock` (nfp_gpu_taichi.py:41)
   - Serializes all GPU kernel launches

### Cancellation

- Flag-based: `NestingController.cancel_requested` (line 277)
- Checked via `cancel_callback()` at each part in `_nest_standard()` (line 304)
- Checked at each generation in `GACoordinator.run()` (line 101)
- NOT checked during inner NFP computation — a single part's placement can't be cancelled

---

## FreeCAD Threading Constraints (CRITICAL)

1. **Document model is NOT thread-safe** — all `doc.addObject()`, `doc.removeObject()`, `obj.Shape = ...`, `obj.ViewObject.*` must happen on the **main thread**
2. Use `FreeCADGui.updateGui()` to yield to event loop — **never** `QApplication.processEvents()` (re-entrant signals)
3. FreeCAD objects are reference-based — they can be deleted by other operations at any time
4. `FreeCADGui.updateGui()` only works when called from the main thread
5. PySide signals with `Qt.QueuedConnection` are safe for cross-thread communication

## Document Operations That Must Stay on Main Thread

These operations in the nesting pipeline modify the FreeCAD document and must NOT be called from a worker thread:

| Operation | Location | Notes |
|-----------|----------|-------|
| `sheet.draw()` | ga_coordinator.py:222 | Creates/modifies Part::Feature objects |
| `LayoutManager.create_ga_population()` | ga_coordinator.py:90 | Creates layout groups in document |
| `LayoutManager.delete_layout()` | ga_coordinator.py:148,162,240,242 | Removes doc objects |
| `_build_next_generation()` | ga_coordinator.py:231 | Creates/deletes layouts |
| `viz_manager.draw_trial_placement()` | visualization_manager.py:15 | Creates Part::Feature |
| `viz_manager.highlight_master()` | visualization_manager.py:74 | Modifies ViewObject |
| `nester.update_callback` (simulate) | nesting_logic.py:133 | Calls sheet.draw() + updateGui() |
| `doc.recompute()` | ga_coordinator.py:153 | Full document recompute |

## Pure Computation (Safe for Worker Thread)

These operations do NOT touch FreeCAD and are safe for any thread:

| Operation | Location |
|-----------|----------|
| `nest()` → `Nester._nest_standard()` | nesting_logic.py:137, nesting_strategy.py:283 |
| `PlacementOptimizer.find_best_placement()` | nesting_strategy.py:36-124 |
| `MinkowskiEngine.get_global_nfp_for()` | minkowski_engine.py:127-278 |
| `MinkowskiEngine._calculate_and_cache_nfp()` | minkowski_engine.py:561-590 |
| `Shape.nfp_cache` reads/writes (with lock) | shape.py:35-36 |
| `LayoutManager.calculate_efficiency()` | layout_manager.py |
| GA operators (crossover, mutation, selection) | genetic_utils.py |

## Key Design Pattern: Compute/Draw Split

To move nesting off the main thread, the `_run_generation()` method must be split:

```
Worker Thread (QThread):
  for each layout:
    nest()                          # pure computation
    calculate_efficiency()          # pure computation
    emit draw_signal(sheet_data)    # request main thread to draw
    sync_event.wait()               # block until main thread finishes drawing

Main Thread (signal handler):
  on draw_signal:
    sheet.draw()                    # document mutation
    FreeCADGui.updateGui()          # event loop yield
    sync_event.set()                # unblock worker
```

## Gotchas

- `FreeCAD.Console.PrintMessage()` is thread-safe — can be called from any thread
- `Shape.nfp_cache` persists across nesting runs (class-level) — thread pool shutdown must not clear it prematurely
- The `_precompute_pool.shutdown(wait=False)` at nesting_strategy.py:364 leaves background tasks running — these write to `Shape.nfp_cache` which is fine (thread-safe) but the pool reference itself must not be garbage-collected while tasks are pending
- Simulation mode binds callbacks (nesting_logic.py:123-125) that call FreeCAD APIs — these must be marshalled to main thread when running in QThread
- `NestingJob.from_ga_result()` at ga_coordinator.py:284 stores references to layout groups — these must be valid FreeCAD objects (created on main thread)
