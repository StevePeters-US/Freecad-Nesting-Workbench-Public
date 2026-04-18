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
        self.layout_manager = None

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
            rotation_params, algo_kwargs, is_simulating, viz_manager=None):
        """
        Execute the GA optimization and return a NestingJob for the winner.

        Returns:
            NestingJob — ready to commit or cancel
        """
        generations = algo_kwargs.get('generations', 1)
        population_size = algo_kwargs.get('population_size', 1)
        rotation_steps = ui_params.get('rotation_steps', 1)
        elite_count = max(2, population_size // 5)
        mutation_rate = 0.1
        immigrant_ratio = 0.15
        early_stop_threshold = 5
        verbose = algo_kwargs.get('verbose', False)
        cancel_callback = algo_kwargs.get('cancel_callback', lambda: False)
        
        if verbose:
            FreeCAD.Console.PrintMessage(f"GA Mode: {generations} generations, {population_size} population\n")
        
        self.layout_manager = LayoutManager(self.doc, self.shape_preparer.processed_shape_cache)
        
        self._set_status(f"Creating {population_size} layouts...")
        FreeCADGui.updateGui()
        
        layouts = self.layout_manager.create_ga_population(
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
                
                gen_time, interrupted = self._run_generation(
                    layouts, gen, generations, ui_params, rotation_steps, 
                    algo_kwargs, is_simulating, cancel_callback, verbose, viz_manager
                )
                total_nesting_time += gen_time
                if interrupted: break

                # Evaluate progress
                layouts.sort(key=lambda l: l.fitness)
                current_best = layouts[0]
                
                if best_layout is None or current_best.fitness < best_layout.fitness:
                    best_layout = current_best
                    best_efficiency = current_best.efficiency
                    generations_without_improvement = 0
                    if verbose:
                        FreeCAD.Console.PrintMessage(f"\n>>> New Best: {best_efficiency:.1f}% efficiency <<<\n")
                else:
                    generations_without_improvement += 1
                    if verbose:
                        FreeCAD.Console.PrintMessage(f"\nNo improvement ({generations_without_improvement}/{early_stop_threshold})\n")
                
                if generations_without_improvement >= early_stop_threshold:
                    FreeCAD.Console.PrintMessage(f"Early stopping: no improvement for {early_stop_threshold} generations\n")
                    break
                
                # STEP 2 & 3: Build next generation
                if gen < generations - 1:
                    actual_elite = min(elite_count, len(layouts))
                    elites = layouts[:actual_elite]
                    layouts = self._build_next_generation(
                        gen, layouts, elites, master_map, quantities, ui_params, 
                        rotation_steps, mutation_rate, immigrant_ratio, verbose
                    )
                else:
                    # Final cleanup
                    for layout in layouts:
                        if layout != best_layout:
                            self.layout_manager.delete_layout(layout, verbose=verbose)
                    layouts = [best_layout]
            
            # STEP 4: Finalize result
            job = self._finalize(best_layout, best_efficiency, total_nesting_time, target_layout, ui_params)
            self.doc.recompute()
            return job
            
        except Exception as e:
            import traceback
            FreeCAD.Console.PrintError(f"GA Nesting Error: {e}\n{traceback.format_exc()}\n")
            self._set_status(f"Error: {e}")
            if 'layouts' in locals():
                for layout in layouts:
                    self.layout_manager.delete_layout(layout)
            self.doc.recompute()
            return None

    def _run_generation(self, layouts, gen, generations, ui_params, rotation_steps, algo_kwargs, 
                        is_simulating, cancel_callback, verbose, viz_manager=None):
        """Nests each layout in the population and calculates fitness/efficiency."""
        from .nesting_logic import nest
        total_time = 0
        
        for idx, layout in enumerate(layouts):
            if cancel_callback(): return total_time, True

            if verbose:
                FreeCAD.Console.PrintMessage(f"  [Gen {gen+1}] Layout {idx+1}/{len(layouts)}: {layout.name}\n")

            if layout.sheets: continue
            if not layout.parts:
                layout.fitness, layout.efficiency = float('inf'), 0
                continue
            
            # Run nesting
            current_kwargs = algo_kwargs.copy()
            if len(layouts) > 1 or generations > 1:
                 current_kwargs['quiet'] = True
                 if 'progress_callback' in current_kwargs: del current_kwargs['progress_callback']
            if layout.genes: current_kwargs['sort'] = False
            
            sheets, unplaced, _, elapsed = nest(
                layout.parts, ui_params['sheet_width'], ui_params['sheet_height'],
                rotation_steps, is_simulating, algorithm=ui_params.get('algorithm', 'Minkowski'),
                viz_manager=viz_manager, **current_kwargs
            )

            if not is_simulating:
                 original_parts_map = {p.id: p for p in layout.parts}
                 for s in sheets:
                     for i, placed_part in enumerate(s.parts):
                          original_part = original_parts_map[placed_part.shape.id]
                          original_part.placement = placed_part.shape.get_final_placement(s.get_origin())
                          s.parts[i].shape = original_part
            total_time += elapsed
            layout.sheets, layout.unplaced = sheets, unplaced

            # Capture genes
            if is_simulating:
                layout.genes = [(p.id, getattr(p, '_angle', 0)) for p in layout.parts] if layout.parts else []
            else:
                gene_map = {placed_part.shape.id: getattr(placed_part.shape, '_angle', 0) 
                            for s in layout.sheets for placed_part in s.parts}
                layout.genes = [(p.id, gene_map.get(p.id, getattr(p, '_angle', 0)))
                                for p in layout.parts] if layout.parts else []
            
            # Efficiency/Fitness
            self.layout_manager.calculate_efficiency(layout, ui_params['sheet_width'], ui_params['sheet_height'])
            if unplaced:
                layout.fitness += len(unplaced) * ui_params['sheet_width'] * ui_params['sheet_height'] * 10
            
            # Draw
            for sheet in sheets:
                sheet.draw(self.doc, ui_params, layout.layout_group, 
                           parts_to_place_group=layout.parts_group, verbose=verbose)
            
            if len(layouts) > 1 and layout.layout_group and hasattr(layout.layout_group, "ViewObject"):
                layout.layout_group.ViewObject.Visibility = False
            FreeCADGui.updateGui()
            
        return total_time, False

    def _build_next_generation(self, gen, layouts, elites, master_map, quantities, ui_params, 
                               rotation_steps, mutation_rate, immigrant_ratio, verbose):
        """Handles selection, crossover, mutation, and immigrants."""
        import random
        from .algorithms import genetic_utils
        
        ranked_pool = [(e.fitness, e.genes) for e in elites if e.genes]
        new_layouts = [elites[0]] # Champion carries forward

        for e in elites[1:]: self.layout_manager.delete_layout(e, verbose=verbose)
        for layout in layouts:
            if layout not in elites: self.layout_manager.delete_layout(layout, verbose=verbose)

        population_size = len(layouts)
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
            new_layouts.append(self.layout_manager.create_layout(
                f"Layout_GA_{gen+2}_c{i+1}", master_map, quantities, ui_params, chromosome_ordering=child_genes
            ))

        for i in range(n_immigrants):
            imm = self.layout_manager.create_layout(f"Layout_GA_{gen+2}_i{i+1}", master_map, quantities, ui_params)
            if imm.parts:
                random.shuffle(imm.parts)
                if rotation_steps > 1:
                    for part in imm.parts: part.set_rotation(random.randrange(rotation_steps) * (360.0 / rotation_steps))
            new_layouts.append(imm)
        return new_layouts

    def _finalize(self, best_layout, best_efficiency, total_time, target_layout, ui_params):
        """Prepares the final NestingJob from the best layout."""
        from .nesting_controller import NestingJob
        if not best_layout: return None
            
        if best_layout.layout_group and hasattr(best_layout.layout_group, "ViewObject"):
            best_layout.layout_group.ViewObject.Visibility = True
        
        if best_layout.layout_group and hasattr(best_layout.layout_group, "Group"):
            for child in best_layout.layout_group.Group:
                if child.Label.startswith("MasterShapes") and hasattr(child, "ViewObject"):
                    child.ViewObject.Visibility = False
        
        best_layout.layout_group.Label = "Layout_temp"
        job = NestingJob.from_ga_result(
            doc=self.doc, target_layout=target_layout, params=ui_params, preparer=self.shape_preparer,
            layout_group=best_layout.layout_group, parts_group=best_layout.parts_group, sheets=best_layout.sheets
        )
        
        c_score = f", Contact: {best_layout.contact_score:.1f}" if hasattr(best_layout, 'contact_score') else ""
        unplaced_count = len(getattr(best_layout, 'unplaced', []) or [])
        placed_count = sum(len(s) for s in best_layout.sheets)
        msg = f"GA Complete: {best_efficiency:.1f}% efficiency, {len(best_layout.sheets)} sheets, {placed_count} placed"
        if unplaced_count: msg += f", {unplaced_count} UNPLACED"
        msg += f"{c_score}, Time: {total_time:.2f}s"
        
        self._set_status(msg)
        FreeCAD.Console.PrintMessage(f"{msg}\n")
        if unplaced_count:
            FreeCAD.Console.PrintWarning(f"WARNING: {unplaced_count} part(s) could not be placed: {[p.id for p in best_layout.unplaced]}\n")
        FreeCAD.Console.PrintMessage(f"--- NESTING DONE ---\n")
        self._play_sound()
        return job
