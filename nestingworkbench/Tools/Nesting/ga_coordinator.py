"""
Coordinates the Genetic Algorithm nesting loop.
Extracted from NestingController._execute_ga_nesting() to follow SRP.
"""
import FreeCAD
import FreeCADGui
import math
import random
from PySide import QtGui
from .layout_manager import LayoutManager
from .algorithms import genetic_utils
# Avoid circular import by importing nest inside the method Or carefully

class GACoordinator:
    """Runs the GA optimization loop and returns the best Layout."""

    def __init__(self, doc, shape_preparer, ui_callbacks=None):
        """
        Args:
            doc: FreeCAD.ActiveDocument
            shape_preparer: ShapePreparer instance (for processed_shape_cache)
            ui_callbacks: dict with optional keys:
                'set_status': callable(str) — update status label
                'update_progress': callable(current, total, msg) — update progress bar
                'reset_progress': callable() — reset progress bar
                'play_sound': callable() — beep on completion
        """
        self.doc = doc
        self.shape_preparer = shape_preparer
        self.ui_callbacks = ui_callbacks or {}

    def _set_status(self, msg):
        callback = self.ui_callbacks.get('set_status')
        if callback:
            try:
                callback(msg)
            except RuntimeError:
                pass

    def _update_progress(self, current, total, msg=None):
        callback = self.ui_callbacks.get('update_progress')
        if callback:
            try:
                callback(current, total, msg)
            except RuntimeError:
                pass

    def _reset_progress(self):
        callback = self.ui_callbacks.get('reset_progress')
        if callback:
            try:
                callback()
            except RuntimeError:
                pass

    def _play_sound(self):
        callback = self.ui_callbacks.get('play_sound')
        if callback:
            try:
                callback()
            except RuntimeError:
                pass

    def run(self, target_layout, ui_params, quantities, master_map,
            rotation_params, algo_kwargs, is_simulating):
        """
        Execute the GA optimization and return a NestingJob for the winner.

        Returns:
            NestingJob — ready to commit or cancel
        """
        # Note: NestingJob is imported here to avoid circular dependency
        from .nesting_controller import NestingJob
        from .nesting_logic import nest

        generations = algo_kwargs.get('generations', 1)
        population_size = algo_kwargs.get('population_size', 1)
        rotation_steps = ui_params.get('rotation_steps', 1)
        elite_count = max(2, population_size // 5)  # Keep top 20%, minimum 2 for crossover
        mutation_rate = 0.1
        immigrant_ratio = 0.15  # 15% of new generation are random immigrants
        early_stop_threshold = 5
        verbose = algo_kwargs.get('verbose', False)
        cancel_callback = algo_kwargs.get('cancel_callback', lambda: False)
        
        if verbose:
            FreeCAD.Console.PrintMessage(f"GA Mode: {generations} generations, {population_size} population\n")
        
        # Create LayoutManager
        layout_manager = LayoutManager(self.doc, self.shape_preparer.processed_shape_cache)
        
        # STEP 1: Create initial population of layouts
        self._set_status(f"Creating {population_size} layouts...")
        FreeCADGui.updateGui()
        
        layouts = layout_manager.create_ga_population(
            master_map, quantities, ui_params, population_size, rotation_steps, verbose=verbose
        )
        
        best_layout = None
        best_efficiency = 0
        generations_without_improvement = 0
        total_nesting_time = 0
        
        try:
            for gen in range(generations):
                if cancel_callback():
                    FreeCAD.Console.PrintMessage("Nesting cancelled by user.\n")
                    break

                if verbose:
                    FreeCAD.Console.PrintMessage(f"\n=== Generation {gen+1}/{generations} ===\n")
                self._set_status(f"Generation {gen+1}/{generations}...")
                FreeCADGui.updateGui()
                
                # Debug: show all layouts with their part counts
                if verbose:
                    FreeCAD.Console.PrintMessage(f"  Layouts to evaluate: {len(layouts)}\n")
                    for i, lay in enumerate(layouts):
                        part_ids = [p.id for p in lay.parts] if lay.parts else []
                        FreeCAD.Console.PrintMessage(f"    {i+1}. {lay.name}: {part_ids}\n")
                
                # Run nesting on each layout
                for idx, layout in enumerate(layouts):
                    if cancel_callback():
                        FreeCAD.Console.PrintMessage("Nesting cancelled by user.\n")
                        break

                    if verbose:
                        FreeCAD.Console.PrintMessage(f"  [Gen {gen+1}] Layout {idx+1}/{len(layouts)}: {layout.name}\n")

                    # Skip if already nested (e.g., winner from previous generation)
                    if layout.sheets:
                        if verbose:
                            FreeCAD.Console.PrintMessage(f"    -> Already nested (winner from previous gen), efficiency: {layout.efficiency:.1f}%\n")
                        continue
                    
                    if not layout.parts:
                        layout.fitness = float('inf')
                        layout.efficiency = 0
                        continue
                    
                    # Run nesting
                    current_algo_kwargs = algo_kwargs.copy()
                    if population_size > 1 or generations > 1:
                         # In GA mode, don't spam the fine-grained progress bar,
                         # just use the status label updates we already have in the loop.
                         current_algo_kwargs['quiet'] = True
                         if 'progress_callback' in current_algo_kwargs:
                             del current_algo_kwargs['progress_callback']
                    # Honour gene ordering for layouts that have pre-set chromosome ordering
                    if layout.genes:
                        current_algo_kwargs['sort'] = False
                    
                    sheets, unplaced, _, elapsed = nest(
                        layout.parts,
                        ui_params['sheet_width'],
                        ui_params['sheet_height'],
                        rotation_steps,
                        is_simulating,
                        algorithm=ui_params.get('algorithm', 'Minkowski'),
                        **current_algo_kwargs
                    )

                    # FIX: If not simulating, we need to manually apply the placement
                    # from the nested copies back to the original layout.parts
                    # because GA nesting bypasses NestingJob.run
                    if not is_simulating:
                         original_parts_map = {p.id: p for p in layout.parts}
                         for s in sheets:
                             for i, placed_part in enumerate(s.parts):
                                  original_part = original_parts_map[placed_part.shape.id]
                                  original_part.placement = placed_part.shape.get_final_placement(s.get_origin())
                                  s.parts[i].shape = original_part
                    total_nesting_time += elapsed
                    
                    layout.sheets = sheets
                    layout.unplaced = unplaced  # Track unplaced parts

                    # Capture genes AFTER nesting so angles reflect optimizer-assigned values
                    if is_simulating:
                        layout.genes = [(p.id, getattr(p, '_angle', 0)) for p in layout.parts] if layout.parts else []
                    else:
                        # non-sim path: nest() uses deepcopy; read angles from placed parts in sheets
                        gene_map = {}
                        for s in layout.sheets:
                            for placed_part in s.parts:
                                pid = placed_part.shape.id
                                gene_map[pid] = getattr(placed_part.shape, '_angle', 0)
                        layout.genes = [(p.id, gene_map.get(p.id, getattr(p, '_angle', 0)))
                                        for p in layout.parts] if layout.parts else []
                    
                    # Calculate efficiency
                    fitness, efficiency = layout_manager.calculate_efficiency(
                        layout, ui_params['sheet_width'], ui_params['sheet_height']
                    )
                    
                    # Penalize unplaced parts
                    if unplaced:
                        layout.fitness += len(unplaced) * ui_params['sheet_width'] * ui_params['sheet_height'] * 10
                        unplaced_ids = [p.id for p in unplaced]
                        FreeCAD.Console.PrintWarning(f"    -> WARNING: {len(unplaced)} part(s) could not be placed: {unplaced_ids}\n")
                    
                    if verbose:
                        FreeCAD.Console.PrintMessage(f"    -> Efficiency: {efficiency:.1f}%\n")
                    
                    # Draw the layout (no offset - we'll delete non-winners)
                    for sheet in sheets:
                        sheet.draw(self.doc, ui_params, layout.layout_group, 
                                   parts_to_place_group=layout.parts_group, verbose=verbose)
                    
                    # Hide completed layout to reduce visual clutter (when population > 1)
                    if population_size > 1 and layout.layout_group and hasattr(layout.layout_group, "ViewObject"):
                        layout.layout_group.ViewObject.Visibility = False
                    
                    FreeCADGui.updateGui()
                
                # Sort by fitness (lower is better)
                layouts.sort(key=lambda l: l.fitness)
                
                current_best = layouts[0]
                if best_layout is None or current_best.fitness < best_layout.fitness:
                    best_layout = current_best
                    best_efficiency = current_best.efficiency
                    generations_without_improvement = 0
                    if verbose:
                        FreeCAD.Console.PrintMessage(f"\n>>> New Best: {best_efficiency:.1f}% efficiency <<<\n")
                        FreeCAD.Console.PrintMessage(f"    Best genes: {best_layout.genes[:5]}... ({len(best_layout.genes)} total)\n")
                        if hasattr(best_layout, 'contact_score'):
                            FreeCAD.Console.PrintMessage(f"    Contact score: {best_layout.contact_score:.1f}\n")
                else:
                    generations_without_improvement += 1
                    if verbose:
                        FreeCAD.Console.PrintMessage(f"\nNo improvement ({generations_without_improvement}/{early_stop_threshold})\n")
                
                # Early stopping
                if generations_without_improvement >= early_stop_threshold:
                    FreeCAD.Console.PrintMessage(f"Early stopping: no improvement for {early_stop_threshold} generations\n")
                    break
                
                # Hide winner (we'll show it at the end)
                if best_layout and best_layout.layout_group:
                    if hasattr(best_layout.layout_group, "ViewObject"):
                        best_layout.layout_group.ViewObject.Visibility = False

                # STEP 2: Select elite pool
                actual_elite = min(elite_count, len(layouts))
                elites = layouts[:actual_elite]  # already sorted by fitness
                if verbose:
                    FreeCAD.Console.PrintMessage(
                        f"  Elites ({actual_elite}): " +
                        ", ".join(f"{e.name}({e.efficiency:.1f}%)" for e in elites) + "\n"
                    )

                # STEP 3: Build next generation
                if gen < generations - 1:
                    ranked_pool = [(e.fitness, e.genes) for e in elites if e.genes]

                    # Champion carries forward with sheets intact (skip re-nesting next gen)
                    new_layouts = [elites[0]]

                    # Delete non-champion elites' FreeCAD objects (genes already captured)
                    for e in elites[1:]:
                        layout_manager.delete_layout(e, verbose=verbose)
                    for layout in layouts:
                        if layout not in elites:
                            layout_manager.delete_layout(layout, verbose=verbose)

                    # Offspring via crossover + mutation
                    n_immigrants = max(1, int((population_size - 1) * immigrant_ratio))
                    n_offspring = max(0, (population_size - 1) - n_immigrants)

                    for i in range(n_offspring):
                        k = min(3, len(ranked_pool))
                        if len(ranked_pool) >= 2:
                            p1 = genetic_utils.tournament_selection(ranked_pool, k=k)
                            p2 = genetic_utils.tournament_selection(ranked_pool, k=k)
                            child_genes = genetic_utils.crossover_genes(p1, p2)
                        else:
                            child_genes = list(ranked_pool[0][1]) if ranked_pool else []
                        child_genes = genetic_utils.mutate_genes(child_genes, mutation_rate, rotation_steps)
                        child_layout = layout_manager.create_layout(
                            f"Layout_GA_{gen+2}_c{i+1}",
                            master_map, quantities, ui_params,
                            chromosome_ordering=child_genes
                        )
                        new_layouts.append(child_layout)

                    # Random immigrants for diversity
                    for i in range(n_immigrants):
                        imm = layout_manager.create_layout(
                            f"Layout_GA_{gen+2}_i{i+1}",
                            master_map, quantities, ui_params
                        )
                        if imm.parts:
                            random.shuffle(imm.parts)
                            if rotation_steps > 1:
                                for part in imm.parts:
                                    angle = random.randrange(rotation_steps) * (360.0 / rotation_steps)
                                    part.set_rotation(angle)
                        new_layouts.append(imm)

                    layouts = new_layouts
                else:
                    # Last generation — delete all non-winners
                    for layout in layouts:
                        if layout != best_layout:
                            layout_manager.delete_layout(layout, verbose=verbose)
                    layouts = [best_layout]
            
            # STEP 4: Final result - winner becomes Layout_temp
            FreeCAD.Console.PrintMessage(f"\n=== Best Solution: {best_efficiency:.1f}% efficiency ===\n")
            
            # Show and rename best layout, set as current job's temp_layout
            if best_layout:
                # Make winner visible
                if best_layout.layout_group and hasattr(best_layout.layout_group, "ViewObject"):
                    best_layout.layout_group.ViewObject.Visibility = True
                
                # Hide MasterShapes group to keep view clean
                if best_layout.layout_group and hasattr(best_layout.layout_group, "Group"):
                    for child in best_layout.layout_group.Group:
                        if child.Label.startswith("MasterShapes") and hasattr(child, "ViewObject"):
                            child.ViewObject.Visibility = False
                
                best_layout.layout_group.Label = "Layout_temp"
                
                job = NestingJob.from_ga_result(
                    doc=self.doc,
                    target_layout=target_layout,
                    params=ui_params,
                    preparer=self.shape_preparer,
                    layout_group=best_layout.layout_group,
                    parts_group=best_layout.parts_group,
                    sheets=best_layout.sheets
                )
                
                # Print final summary at the very end of the report
                c_score = f", Contact: {best_layout.contact_score:.1f}" if hasattr(best_layout, 'contact_score') else ""
                unplaced_count = len(getattr(best_layout, 'unplaced', []) or [])
                placed_count = sum(len(s) for s in best_layout.sheets)
                unplaced_msg = f", {unplaced_count} UNPLACED" if unplaced_count > 0 else ""
                msg = f"GA Complete: {best_efficiency:.1f}% efficiency, {len(best_layout.sheets)} sheets, {placed_count} placed{unplaced_msg}{c_score}, Time: {total_nesting_time:.2f}s"
                self._set_status(msg)
                FreeCAD.Console.PrintMessage(f"{msg}\n")
                if unplaced_count > 0:
                    unplaced_ids = [p.id for p in best_layout.unplaced]
                    FreeCAD.Console.PrintWarning(f"WARNING: {unplaced_count} part(s) could not be placed: {unplaced_ids}\n")
                FreeCAD.Console.PrintMessage(f"--- NESTING DONE ---\n")
                self._play_sound()
                
                self.doc.recompute()
                return job
            
            self.doc.recompute()
            return None
            
        except Exception as e:
            FreeCAD.Console.PrintError(f"GA Nesting Error: {e}\n")
            import traceback
            traceback.print_exc()
            try:
                self._set_status(f"Error: {e}")
            except RuntimeError: pass
            # Cleanup all remaining layouts on error
            for layout in layouts:
                layout_manager.delete_layout(layout)
            self.doc.recompute()
            return None
