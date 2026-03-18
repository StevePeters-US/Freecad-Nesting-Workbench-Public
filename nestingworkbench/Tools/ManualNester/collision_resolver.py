"""
Collision resolver for the manual nesting tool.
Handles clamping parts to sheet boundaries and basic overlap resolution.
"""

class CollisionResolver:
    def clamp_to_sheet(self, obj, sheet_bbox):
        """
        Adjusts obj.Placement.Base so obj's BoundBox stays within sheet_bbox.
        """
        bb, ox, oy = self._find_bbox(obj)
        if not bb:
            return False
            
        current_pos = obj.Placement.Base
        
        # Absolute min/max includes object placement + accumulated internal offset + bb local bounds
        obj_min_x = current_pos.x + ox + bb.XMin
        obj_max_x = current_pos.x + ox + bb.XMax
        obj_min_y = current_pos.y + oy + bb.YMin
        obj_max_y = current_pos.y + oy + bb.YMax
        
        new_x = current_pos.x
        new_y = current_pos.y
        clamped = False
        
        # Check X boundaries
        if obj_min_x < sheet_bbox.XMin:
            new_x += (sheet_bbox.XMin - obj_min_x)
            clamped = True
        elif obj_max_x > sheet_bbox.XMax:
            new_x -= (obj_max_x - sheet_bbox.XMax)
            clamped = True
            
        # Check Y boundaries
        if obj_min_y < sheet_bbox.YMin:
            new_y += (sheet_bbox.YMin - obj_min_y)
            clamped = True
        elif obj_max_y > sheet_bbox.YMax:
            new_y -= (obj_max_y - sheet_bbox.YMax)
            clamped = True
            
        if clamped:
            # Recreate vector using the same type as current_pos to avoid FreeCAD dependency here
            obj.Placement.Base = type(current_pos)(new_x, new_y, current_pos.z)
            
        return clamped

    def separate_overlapping(self, moved_obj, other_objs, max_iterations=5):
        """
        Iteratively separates moved_obj from overlapping other_objs.
        Only moved_obj is shifted.
        """
        for i in range(max_iterations):
            any_overlap = False
            moved_bb = self._get_abs_bbox(moved_obj)
            if not moved_bb:
                return False
            current_pos = moved_obj.Placement.Base
            
            for other in other_objs:
                if other == moved_obj:
                    continue
                
                other_bb = self._get_abs_bbox(other)
                if not other_bb:
                    continue
                
                if self._bboxes_intersect(moved_bb, other_bb):
                    any_overlap = True
                    # Calculate separation (XY only)
                    overlap_x = min(moved_bb['max_x'], other_bb['max_x']) - max(moved_bb['min_x'], other_bb['min_x']) + 0.001
                    overlap_y = min(moved_bb['max_y'], other_bb['max_y']) - max(moved_bb['min_y'], other_bb['min_y']) + 0.001
                    
                    new_x = current_pos.x
                    new_y = current_pos.y
                    
                    if overlap_x < overlap_y:
                        # Push along X
                        dir_x = 1.0 if moved_bb['center_x'] > other_bb['center_x'] else -1.0
                        new_x += overlap_x * dir_x
                    else:
                        # Push along Y
                        dir_y = 1.0 if moved_bb['center_y'] > other_bb['center_y'] else -1.0
                        new_y += overlap_y * dir_y
                    
                    current_pos = type(current_pos)(new_x, new_y, current_pos.z)
                    moved_obj.Placement.Base = current_pos
                    moved_bb = self._get_abs_bbox(moved_obj)
            
            if not any_overlap:
                return True
        return False

    def resolve_bi_collision(self, obj_a, obj_b):
        """Symmetrically separates two objects. Returns True if they were overlapping."""
        bb_a = self._get_abs_bbox(obj_a)
        bb_b = self._get_abs_bbox(obj_b)
        if not bb_a or not bb_b:
            return False
            
        if self._bboxes_intersect(bb_a, bb_b):
            ox = min(bb_a['max_x'], bb_b['max_x']) - max(bb_a['min_x'], bb_b['min_x']) + 0.001
            oy = min(bb_a['max_y'], bb_b['max_y']) - max(bb_a['min_y'], bb_b['min_y']) + 0.001
            
            if ox < oy:
                shift = ox / 2.0
                dir_x = 1.0 if bb_a['center_x'] > bb_b['center_x'] else -1.0
                # Must use explicit assignment — Placement.Base returns a copy,
                # so += modifies the copy without setting it back via the property setter.
                obj_a.Placement.Base = obj_a.Placement.Base + type(obj_a.Placement.Base)(shift * dir_x, 0, 0)
                obj_b.Placement.Base = obj_b.Placement.Base + type(obj_b.Placement.Base)(-shift * dir_x, 0, 0)
            else:
                shift = oy / 2.0
                dir_y = 1.0 if bb_a['center_y'] > bb_b['center_y'] else -1.0
                obj_a.Placement.Base = obj_a.Placement.Base + type(obj_a.Placement.Base)(0, shift * dir_y, 0)
                obj_b.Placement.Base = obj_b.Placement.Base + type(obj_b.Placement.Base)(0, -shift * dir_y, 0)
            return True
        return False

    def _get_abs_bbox(self, obj):
        """Helper to get absolute bounding box as a dict. Returns None if no bounds found."""
        bb, ox, oy = self._find_bbox(obj)
        if not bb:
            return None
        pos = obj.Placement.Base
        gx = pos.x + ox
        gy = pos.y + oy
        return {
            'min_x': gx + bb.XMin,
            'max_x': gx + bb.XMax,
            'min_y': gy + bb.YMin,
            'max_y': gy + bb.YMax,
            'center_x': gx + bb.XMin + bb.XLength / 2,
            'center_y': gy + bb.YMin + bb.YLength / 2
        }

    def _find_bbox(self, obj):
        """Returns (BoundBox, offset_x, offset_y) relative to local origin of 'obj'."""
        # 1. Prioritize BoundaryObject link
        if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject.Shape, "BoundBox"):
            bb = obj.BoundaryObject.Shape.BoundBox
            pos = obj.BoundaryObject.Placement.Base
            return bb, pos.x, pos.y
            
        # 2. Check for raw Shape
        if hasattr(obj, "Shape") and hasattr(obj.Shape, "BoundBox"):
            return obj.Shape.BoundBox, 0, 0
            
        # 3. Recurse into App::Part containers
        if hasattr(obj, "Group"):
            for child in obj.Group:
                bb, ox, oy = self._find_bbox(child)
                if bb:
                    # accumulation: child's placement + internal child offset
                    cpos = child.Placement.Base
                    return bb, ox + cpos.x, oy + cpos.y
        return None, 0, 0

    def _bboxes_intersect(self, bb1, bb2):
        """Check if two absolute bboxes (dicts) intersect."""
        # Use strict inequality for intersection:
        # If one ends exactly where the next starts, it's not an intersection.
        return not (bb1['max_x'] <= bb2['min_x'] or 
                   bb1['min_x'] >= bb2['max_x'] or 
                   bb1['max_y'] <= bb2['min_y'] or 
                   bb1['min_y'] >= bb2['max_y'])
