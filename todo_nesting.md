# Nesting Threading & Parallelism Tasks

> Move nesting computation off the main thread so the GUI stays responsive and cancellation works instantly. Fix CPU-path parallelism so rotation evaluation actually runs concurrently.

## Skills to Read

- `nw_threading` — threading constraints, compute/draw split pattern, document operation safety
- `nw_nesting_pipeline` — pipeline steps, key APIs
- `nw_nfp_algorithm` — NFP cache architecture, pre-caching flow
- `nw_freecad_patterns` — FreeCAD thread safety rules

## Architecture Overview

```
BEFORE (everything on main thread):

  NestingController.run()  ──[main thread]──>  GACoordinator.run()
                                                    │
                                              _run_generation()
                                                    │
                                              nest() + sheet.draw() + updateGui()
                                                    │
                                              [GUI frozen until done]

AFTER (compute on worker, draw on main):

  NestingController.run()  ──>  start NestingWorker(QThread)
                                       │
                              [worker thread]
                                       │
                              GACoordinator.run()
                                       │
                              _run_generation()
                                       │
                              nest()  ← pure computation
                                       │
                              emit draw_signal ──> [main thread] sheet.draw() + updateGui()
                              wait for sync_event
                                       │
                              [continue next layout]
```

## Reference Code

### PySide QThread + Signals Pattern
```python
from PySide.QtCore import QThread, Signal

class NestingWorker(QThread):
    status_changed = Signal(str)
    progress_updated = Signal(int, int, str)
    finished_signal = Signal(object)
    error_signal = Signal(str)
    
    def __init__(self, run_fn, parent=None):
        super().__init__(parent)
        self._run_fn = run_fn
    
    def run(self):
        try:
            result = self._run_fn()
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))
```

### Blocking Cross-Thread Callback Pattern
```python
import threading

class DrawSynchronizer:
    """Allows worker thread to request main-thread work and wait for completion."""
    def __init__(self):
        self._event = threading.Event()
        self._payload = None
    
    def request_draw(self, payload):
        """Called from worker thread. Blocks until main thread completes draw."""
        self._payload = payload
        self._event.clear()
        # Emit signal to main thread (connected via QueuedConnection)
        self.draw_requested.emit(payload)
        self._event.wait()  # Block worker until main thread signals done
    
    def draw_complete(self):
        """Called from main thread after draw finishes."""
        self._event.set()
```

---

## Tasks

### N-001: Create NestingWorker QThread class

- [x] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` (MODIFY)
- **What**: Add a `NestingWorker(QThread)` class that runs the nesting computation on a background thread and communicates with the main thread via Qt signals.
- **Skill**: `nw_threading`
- **Lines changed**: ~60

**Add this class before the `NestingController` class (around line 20, after imports):**

```python
import threading
from PySide.QtCore import QThread, Signal

class NestingWorker(QThread):
    """Runs nesting computation on a background thread.
    
    Communicates with main thread via Qt signals for:
    - Status/progress updates (non-blocking)
    - Document operations like sheet.draw() (blocking synchronization)
    - Completion/error reporting
    """
    status_changed = Signal(str)
    progress_updated = Signal(int, int, str)   # current, total, message
    draw_requested = Signal(object)             # payload dict for main-thread drawing
    finished_signal = Signal(object)            # NestingJob result (or None)
    error_signal = Signal(str)                  # error message + traceback
    
    def __init__(self, coordinator, run_args, cancel_check_fn, parent=None):
        """
        Args:
            coordinator: GACoordinator instance
            run_args: tuple of (target_layout, ui_params, quantities, master_map,
                      rotation_params, algo_kwargs, is_simulating, viz_manager)
            cancel_check_fn: callable that returns True if cancel requested
        """
        super().__init__(parent)
        self.coordinator = coordinator
        self.run_args = run_args
        self.cancel_check_fn = cancel_check_fn
        self._draw_event = threading.Event()
    
    def run(self):
        """Execute nesting on worker thread."""
        try:
            (target_layout, ui_params, quantities, master_map,
             rotation_params, algo_kwargs, is_simulating, viz_manager) = self.run_args
            
            job = self.coordinator.run(
                target_layout, ui_params, quantities, master_map,
                rotation_params, algo_kwargs, is_simulating, viz_manager=viz_manager
            )
            self.finished_signal.emit(job)
        except Exception as e:
            import traceback
            self.error_signal.emit(f"{e}\n{traceback.format_exc()}")
    
    def request_draw_on_main_thread(self, payload):
        """Called from worker thread. Emits signal and blocks until main thread draws."""
        self._draw_event.clear()
        self.draw_requested.emit(payload)
        self._draw_event.wait()
    
    def notify_draw_complete(self):
        """Called from main thread after draw finishes."""
        self._draw_event.set()
```

---

### N-002: Refactor GACoordinator to accept draw callback

- [x] **File**: `nestingworkbench/Tools/Nesting/ga_coordinator.py` (MODIFY)
- **What**: Add a `draw_callback` parameter to `__init__` and `_run_generation` so drawing can be deferred to the main thread. When no callback is provided, draw inline (backwards compatible).
- **Depends on**: N-001
- **Skill**: `nw_threading`, `nw_nesting_pipeline`
- **Lines changed**: ~40

**Changes:**

1. Add `draw_callback` parameter to `__init__` (line 16):
```python
def __init__(self, doc, shape_preparer, ui_callbacks=None, draw_callback=None):
    ...
    self.draw_callback = draw_callback  # callable(payload_dict) or None
```

2. Replace direct `sheet.draw()` + `updateGui()` in `_run_generation()` (lines 221-227) with:
```python
# Collect draw payload
draw_payload = {
    'sheets': sheets,
    'doc': self.doc,
    'ui_params': ui_params,
    'layout_group': layout.layout_group,
    'parts_group': layout.parts_group,
    'verbose': verbose,
    'hide_layout': len(layouts) > 1,
}

if self.draw_callback:
    self.draw_callback(draw_payload)  # blocks until main thread draws
else:
    # Inline draw (original behavior for non-threaded mode)
    for sheet in sheets:
        sheet.draw(self.doc, ui_params, layout.layout_group,
                   parts_to_place_group=layout.parts_group, verbose=verbose)
    if len(layouts) > 1 and layout.layout_group and hasattr(layout.layout_group, "ViewObject"):
        layout.layout_group.ViewObject.Visibility = False
    FreeCADGui.updateGui()
```

3. Replace direct `FreeCADGui.updateGui()` calls at lines 88, 108 with:
```python
if self.draw_callback:
    self.draw_callback({'updateGui_only': True})
else:
    FreeCADGui.updateGui()
```

---

### N-003: Refactor GACoordinator UI callbacks for thread safety

- [x] **File**: `nestingworkbench/Tools/Nesting/ga_coordinator.py` (MODIFY)
- **What**: Replace direct UI callback invocations (`_set_status`, `_update_progress`) with signal emissions when running in threaded mode. The `NestingWorker` signals handle cross-thread delivery.
- **Depends on**: N-001, N-002
- **Skill**: `nw_threading`
- **Lines changed**: ~25

**Changes:**

1. Add `worker` parameter to `__init__`:
```python
def __init__(self, doc, shape_preparer, ui_callbacks=None, draw_callback=None, worker=None):
    ...
    self.worker = worker  # NestingWorker instance (or None for non-threaded)
```

2. Modify `_set_status` to use worker signal when available:
```python
def _set_status(self, msg):
    if self.worker:
        self.worker.status_changed.emit(msg)
        return
    callback = self.ui_callbacks.get('set_status')
    if callback:
        try: callback(msg)
        except RuntimeError: pass
```

3. Modify `_update_progress` similarly:
```python
def _update_progress(self, current, total, msg=None):
    if self.worker:
        self.worker.progress_updated.emit(current, total, msg or "")
        return
    callback = self.ui_callbacks.get('update_progress')
    if callback:
        try: callback(current, total, msg)
        except RuntimeError: pass
```

---

### N-004: Refactor GACoordinator population creation for thread safety

- [x] **File**: `nestingworkbench/Tools/Nesting/ga_coordinator.py` (MODIFY)
- **What**: Population creation (`create_ga_population` at line 90) and next-generation building (`_build_next_generation` at line 231) create/delete FreeCAD document objects. Marshal these to the main thread via the draw_callback when running threaded.
- **Depends on**: N-002
- **Skill**: `nw_threading`, `nw_freecad_patterns`
- **Lines changed**: ~30

**Changes:**

1. In `run()`, wrap population creation (line 90-92):
```python
if self.draw_callback:
    # Marshal to main thread
    create_payload = {
        'create_population': True,
        'master_map': master_map,
        'quantities': quantities, 
        'ui_params': ui_params,
        'population_size': population_size,
        'rotation_steps': rotation_steps,
        'verbose': verbose,
    }
    self.draw_callback(create_payload)
    layouts = self._pending_layouts  # Set by main thread handler
else:
    layouts = self.layout_manager.create_ga_population(...)
```

2. Similarly wrap `_build_next_generation()` call at line 140-143 and layout deletion at lines 146-148.

3. The main-thread draw handler in NestingController (N-005) will execute these operations and store results back on the coordinator.

---

### N-005: Wire NestingWorker into NestingController

- [x] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` (MODIFY)
- **What**: Refactor `_execute_ga_nesting()` to create and start `NestingWorker` instead of running synchronously. Add signal handler slots for draw, status, progress, completion, and error. Move cleanup logic from `run()`'s `finally` block to signal handlers.
- **Depends on**: N-001, N-002, N-003, N-004
- **Skill**: `nw_threading`, `nw_nesting_pipeline`
- **Lines changed**: ~100

**Changes:**

1. Modify `_execute_ga_nesting()` (line 664-680):
```python
def _execute_ga_nesting(self, target_layout, ui_params, quantities, master_map,
                        rotation_params, algo_kwargs, is_simulating, viz_manager=None):
    """GA optimization on a background thread."""
    
    # Create worker
    self._worker = NestingWorker(
        coordinator=None,  # Set after coordinator is created
        run_args=(target_layout, ui_params, quantities, master_map,
                  rotation_params, algo_kwargs, is_simulating, viz_manager),
        cancel_check_fn=self._check_cancel,
        parent=None
    )
    
    # Create coordinator with draw_callback bound to worker
    coordinator = GACoordinator(
        doc=self.doc,
        shape_preparer=self.shape_preparer,
        ui_callbacks={...},  # same as before
        draw_callback=self._worker.request_draw_on_main_thread,
        worker=self._worker,
    )
    self._worker.coordinator = coordinator
    
    # Connect signals
    self._worker.status_changed.connect(lambda msg: self.ui.status_label.setText(msg))
    self._worker.progress_updated.connect(lambda c, t, m: self.ui.update_progress(c, t, m))
    self._worker.draw_requested.connect(self._handle_draw_request)
    self._worker.finished_signal.connect(self._on_nesting_finished)
    self._worker.error_signal.connect(self._on_nesting_error)
    
    # Start worker
    self._worker.start()
```

2. Modify `run()` (line 341-354) — remove the synchronous `try/finally`:
```python
# Instead of:
#   try:
#       self.is_running = True
#       self._execute_ga_nesting(...)
#   finally:
#       self.is_running = False
#       ...

# Do:
self.is_running = True
self.cancel_requested = False
self.ui.nest_button.setEnabled(False)
self.ui.cancel_button.setEnabled(True)
self._execute_ga_nesting(target_layout, ui_params, quantities, master_map,
                         rotation_params, algo_kwargs, is_simulating, self.viz_manager)
# Returns immediately — cleanup happens in signal handlers
```

3. Add signal handler slots:
```python
def _handle_draw_request(self, payload):
    """Main-thread handler for draw requests from worker."""
    try:
        if payload.get('updateGui_only'):
            FreeCADGui.updateGui()
        elif payload.get('create_population'):
            # Execute population creation on main thread
            layouts = self._worker.coordinator.layout_manager.create_ga_population(
                payload['master_map'], payload['quantities'], 
                payload['ui_params'], payload['population_size'],
                payload['rotation_steps'], verbose=payload.get('verbose', False)
            )
            self._worker.coordinator._pending_layouts = layouts
        elif payload.get('sheets'):
            for sheet in payload['sheets']:
                sheet.draw(payload['doc'], payload['ui_params'], payload['layout_group'],
                          parts_to_place_group=payload['parts_group'], 
                          verbose=payload.get('verbose', False))
            if payload.get('hide_layout'):
                lg = payload['layout_group']
                if lg and hasattr(lg, "ViewObject"):
                    lg.ViewObject.Visibility = False
            FreeCADGui.updateGui()
    finally:
        self._worker.notify_draw_complete()

def _on_nesting_finished(self, job):
    """Main-thread handler for nesting completion."""
    self.current_job = job
    self.is_running = False
    self.cancel_requested = False
    self.ui.nest_button.setEnabled(True)
    self.ui.cancel_button.setEnabled(False)
    self.ui.reset_progress()
    self._worker = None

def _on_nesting_error(self, error_msg):
    """Main-thread handler for nesting errors."""
    FreeCAD.Console.PrintError(f"Nesting Error: {error_msg}\n")
    self.ui.status_label.setText(f"Error: {error_msg.split(chr(10))[0]}")
    self.is_running = False
    self.cancel_requested = False
    self.ui.nest_button.setEnabled(True)
    self.ui.cancel_button.setEnabled(False)
    self.ui.reset_progress()
    self._worker = None
```

---

### N-006: Marshal simulation callbacks for thread safety

- [x] **File**: `nestingworkbench/Tools/Nesting/nesting_logic.py` (MODIFY)
- **What**: When running on a worker thread, the simulation callbacks (`trial_callback`, `part_start_callback`, `update_callback`) call FreeCAD document APIs which must run on the main thread. Wrap these callbacks to use `QTimer.singleShot(0, fn)` for non-blocking main-thread dispatch when called from a worker thread.
- **Depends on**: N-005
- **Skill**: `nw_threading`, `nw_freecad_patterns`
- **Lines changed**: ~25

**Changes:**

1. Add a helper function at module level:
```python
from PySide.QtCore import QThread, QTimer
from PySide.QtWidgets import QApplication

def _main_thread_wrapper(fn):
    """Wraps a callback so it always executes on the main thread."""
    def wrapper(*args, **kwargs):
        if QThread.currentThread() == QApplication.instance().thread():
            fn(*args, **kwargs)
        else:
            QTimer.singleShot(0, lambda: fn(*args, **kwargs))
    return wrapper
```

2. In `nest()`, wrap the simulation callbacks (lines 123-133):
```python
if simulate:
    if viz_manager is None:
        viz_manager = VisualizationManager()
    
    kwargs['trial_callback'] = _main_thread_wrapper(
        lambda p, a, x, y: _visualize_trial_placement(p, a, x, y, viz_manager)
    )
    kwargs['part_start_callback'] = _main_thread_wrapper(
        lambda p: _on_part_start(p, viz_manager)
    )
    kwargs['part_end_callback'] = lambda p, pl: _on_part_end(p, pl, viz_manager)

# ...
if simulate:
    nester.update_callback = _main_thread_wrapper(
        lambda part, sheet: (sheet.draw(FreeCAD.ActiveDocument, {}, transient_part=part), FreeCADGui.updateGui())
    )
```

**Note**: `_main_thread_wrapper` uses fire-and-forget (`QTimer.singleShot`). This means the worker thread does NOT wait for the visualization to complete. This is intentional — simulation visualization is cosmetic and shouldn't block computation.

---

### N-007: Handle cancellation with active worker thread

- [x] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` (MODIFY)
- **What**: Update `request_cancel()` and `cancel_job()` to handle the case where a `NestingWorker` thread is active. The cancel flag is already thread-safe (GIL guarantees atomic bool read), but we need to wait for the worker to actually stop before cleaning up.
- **Depends on**: N-005
- **Skill**: `nw_threading`
- **Lines changed**: ~20

**Changes:**

1. Modify `request_cancel()` (line 705):
```python
def request_cancel(self):
    """Called when the custom Cancel Nesting button is clicked."""
    if self.is_running:
        self.cancel_requested = True
        try:
            self.ui.status_label.setText("Cancelling... Please wait.")
            self.ui.cancel_button.setEnabled(False)  # Prevent double-click
        except Exception:
            pass
        
        # If worker is running, also unblock it from any draw wait
        if hasattr(self, '_worker') and self._worker:
            self._worker.notify_draw_complete()  # Unblock if waiting for draw
    else:
        self.cancel_job()
        if hasattr(self.ui, 'reject'):
            self.ui.reject()
```

2. In `_on_nesting_finished`, handle cancelled state:
```python
def _on_nesting_finished(self, job):
    if self.cancel_requested:
        # Nesting was cancelled — clean up instead of keeping result
        if job:
            job.cleanup()
        self.cancel_job()
    else:
        self.current_job = job
    # ... rest of cleanup
```

---

### N-008: Profile CPU parallelism bottleneck

- [x] **File**: `nestingworkbench/Tools/Nesting/algorithms/nesting_strategy.py` (MODIFY)
- **What**: Add timing instrumentation to the CPU rotation evaluation loop to determine whether the bottleneck is GIL contention, `nfp_cache_lock` contention, or something else. Log per-thread wall time vs total wall time to diagnose.
- **Skill**: `nw_threading`, `nw_nfp_algorithm`
- **Lines changed**: ~20

**Changes:**

Add timing around the ThreadPoolExecutor block in `find_best_placement()` (line 97-114):

```python
# CPU Parallel evaluation
import time
t0_parallel = time.perf_counter()
with ThreadPoolExecutor() as executor:
    angles = [i * (360.0 / part_rotation_steps) for i in range(part_rotation_steps)]
    futures = {
        executor.submit(self._evaluate_rotation, angle, part, placed_parts_grouped, sheet, direction): angle
        for angle in angles
    }
    
    thread_times = {}
    for future in as_completed(futures):
        try:
            res = future.result()
            # ... existing result handling
        except Exception as e:
            self.log(f"Error in rotation evaluation thread: {e}")

dt_parallel = time.perf_counter() - t0_parallel
if self.verbose:
    self.log(f"  -> Parallel eval: {len(angles)} rotations in {dt_parallel*1000:.1f}ms "
             f"(ideal speedup: {len(angles)}x, pool workers: {min(len(angles), os.cpu_count() or 1)})")
```

Also add timing inside `_evaluate_rotation()` (line 126):
```python
def _evaluate_rotation(self, angle, part, placed_parts_grouped, sheet, direction):
    import time, threading
    t0 = time.perf_counter()
    thread_id = threading.current_thread().name
    
    nfp_entry = self.engine.get_global_nfp_for(part, angle, sheet)
    t_nfp = time.perf_counter()
    
    # ... existing candidate scoring ...
    
    t_end = time.perf_counter()
    if self.verbose:
        self.log(f"    [{thread_id}] angle={angle:.0f}: NFP={((t_nfp-t0)*1000):.1f}ms, "
                 f"score={((t_end-t_nfp)*1000):.1f}ms, total={((t_end-t0)*1000):.1f}ms")
    return best
```

**After running with verbose=True**, check:
- If all threads take similar wall time but total is ~= single thread → GIL bottleneck
- If some threads take much longer → lock contention
- If total ≈ max(thread times) → parallelism is working

---

### N-009: Reduce nfp_cache_lock contention

- [x] **File**: `nestingworkbench/datatypes/shape.py` (MODIFY)
- [x] **File**: `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` (MODIFY)  
- **What**: Replace the global `Shape.nfp_cache_lock` with a pattern that reduces contention. The current single lock serializes ALL cache reads/writes across all threads.
- **Depends on**: N-008 (profiling confirms lock contention)
- **Skill**: `nw_threading`, `nw_nfp_algorithm`
- **Lines changed**: ~30

**Option A — Double-checked locking (minimal change):**

Replace lock-guarded reads in `get_global_nfp_for()` (minkowski_engine.py:163-164):
```python
# BEFORE:
with Shape.nfp_cache_lock:
    nfp_data = Shape.nfp_cache.get(nfp_cache_key)

# AFTER (dict.get is atomic under GIL for simple keys):
nfp_data = Shape.nfp_cache.get(nfp_cache_key)
# Only take lock for writes (in _calculate_and_cache_nfp)
```

Python dict reads with immutable keys are effectively atomic under the GIL. The lock is only needed for writes (to prevent lost updates when two threads compute the same NFP). This eliminates read contention entirely.

**Keep the lock for writes** in `_calculate_and_cache_nfp` and `_calculate_and_cache_nfp_gpu` — these are already rare (cache miss path only).
