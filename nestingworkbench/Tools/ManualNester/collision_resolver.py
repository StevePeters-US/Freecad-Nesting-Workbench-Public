"""
Collision resolver for the manual nesting tool.
Handles clamping parts to sheet boundaries and basic overlap resolution.

NOTE: FreeCAD's ``obj.Placement`` returns a **copy**.  Assigning to
``obj.Placement.Base`` silently modifies that copy, leaving the real
object untouched.  Every mutation therefore uses the pattern::

    pl = obj.Placement
    pl.Base = new_value
    obj.Placement = pl          # <-- writes back to the property
"""


def _set_base(obj, new_base):
    """Safely set an object's Placement.Base via full Placement assignment."""
    pl = obj.Placement
    pl.Base = new_base
    obj.Placement = pl


class CollisionResolver:
    def clamp_to_sheet(self, obj, sheet_bbox):
        """
        Adjusts obj.Placement.Base so obj's BoundBox stays within sheet_bbox.
        Uses rotation-aware bounding box computation.
        """
        abs_bb = self._get_abs_bbox(obj)
        if not abs_bb:
            return False

        current_pos = obj.Placement.Base

        new_x = current_pos.x
        new_y = current_pos.y
        clamped = False

        # Check X boundaries
        if abs_bb['min_x'] < sheet_bbox.XMin:
            new_x += (sheet_bbox.XMin - abs_bb['min_x'])
            clamped = True
        elif abs_bb['max_x'] > sheet_bbox.XMax:
            new_x -= (abs_bb['max_x'] - sheet_bbox.XMax)
            clamped = True

        # Check Y boundaries
        if abs_bb['min_y'] < sheet_bbox.YMin:
            new_y += (sheet_bbox.YMin - abs_bb['min_y'])
            clamped = True
        elif abs_bb['max_y'] > sheet_bbox.YMax:
            new_y -= (abs_bb['max_y'] - sheet_bbox.YMax)
            clamped = True

        if clamped:
            _set_base(obj, type(current_pos)(new_x, new_y, current_pos.z))

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
                    _set_base(moved_obj, current_pos)
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
                Vec = type(obj_a.Placement.Base)
                _set_base(obj_a, obj_a.Placement.Base + Vec(shift * dir_x, 0, 0))
                _set_base(obj_b, obj_b.Placement.Base + Vec(-shift * dir_x, 0, 0))
            else:
                shift = oy / 2.0
                dir_y = 1.0 if bb_a['center_y'] > bb_b['center_y'] else -1.0
                Vec = type(obj_a.Placement.Base)
                _set_base(obj_a, obj_a.Placement.Base + Vec(0, shift * dir_y, 0))
                _set_base(obj_b, obj_b.Placement.Base + Vec(0, -shift * dir_y, 0))
            return True
        return False

    def overlaps_any(self, obj, others):
        """Returns True if obj's bbox overlaps any bbox in others."""
        bb = self._get_abs_bbox(obj)
        if not bb:
            return False
        for other in others:
            if other == obj:
                continue
            other_bb = self._get_abs_bbox(other)
            if other_bb and self._bboxes_intersect(bb, other_bb):
                return True
        return False

    def _get_abs_bbox(self, obj):
        """Helper to get absolute bounding box as a dict.

        Transforms the local BoundBox through the full placement chain
        (including rotation) so that the axis-aligned result is correct
        for rotated parts.  Returns None if no bounds found.
        """
        placement, bb = self._find_bbox_with_placement(obj, None)
        if not bb:
            return None
        transformed = self._transform_bbox(bb, placement)
        return {
            'min_x': transformed[0],
            'max_x': transformed[1],
            'min_y': transformed[2],
            'max_y': transformed[3],
            'center_x': (transformed[0] + transformed[1]) / 2,
            'center_y': (transformed[2] + transformed[3]) / 2,
        }

    def _find_bbox_with_placement(self, obj, parent_placement):
        """Returns (accumulated_placement, local_BoundBox) or (None, None).

        Walks BoundaryObject -> Group children -> Shape, accumulating
        placements so the caller can apply the full transform.

        IMPORTANT: Group recursion is checked BEFORE raw Shape because
        App::Part.Shape returns a compound in global coordinates (already
        includes the container's Placement).  Using it with _transform_bbox
        would double-apply the placement, causing mirror/drift on clamp.
        """
        if parent_placement is None:
            current = obj.Placement
        else:
            current = parent_placement.multiply(obj.Placement)

        # 1. Prioritize BoundaryObject link
        if hasattr(obj, "BoundaryObject") and obj.BoundaryObject and hasattr(obj.BoundaryObject.Shape, "BoundBox"):
            full = current.multiply(obj.BoundaryObject.Placement)
            return full, obj.BoundaryObject.Shape.BoundBox

        # 2. Recurse into App::Part / container groups BEFORE raw Shape,
        #    because container.Shape is a global compound (double-transform bug).
        if hasattr(obj, "Group"):
            for child in obj.Group:
                result_placement, result_bb = self._find_bbox_with_placement(child, current)
                if result_bb:
                    return result_placement, result_bb

        # 3. Fallback: raw Shape (only reached for leaf Part::Feature objects)
        if hasattr(obj, "Shape") and hasattr(obj.Shape, "BoundBox"):
            return current, obj.Shape.BoundBox

        return None, None

    @staticmethod
    def _transform_bbox(bb, placement):
        """Transform 4 local BoundBox corners (XY plane) through *placement*
        and return (min_x, max_x, min_y, max_y)."""
        try:
            corners = [
                placement.multVec(type(placement.Base)(bb.XMin, bb.YMin, 0)),
                placement.multVec(type(placement.Base)(bb.XMax, bb.YMin, 0)),
                placement.multVec(type(placement.Base)(bb.XMin, bb.YMax, 0)),
                placement.multVec(type(placement.Base)(bb.XMax, bb.YMax, 0)),
            ]
        except (TypeError, AttributeError, NameError):
            # Fallback: FreeCAD.Vector not available (unit tests)
            import FreeCAD
            corners = [
                placement.multVec(FreeCAD.Vector(bb.XMin, bb.YMin, 0)),
                placement.multVec(FreeCAD.Vector(bb.XMax, bb.YMin, 0)),
                placement.multVec(FreeCAD.Vector(bb.XMin, bb.YMax, 0)),
                placement.multVec(FreeCAD.Vector(bb.XMax, bb.YMax, 0)),
            ]
        xs = [v.x for v in corners]
        ys = [v.y for v in corners]
        return (min(xs), max(xs), min(ys), max(ys))

    def _bboxes_intersect(self, bb1, bb2):
        """Check if two absolute bboxes (dicts) intersect."""
        # Use strict inequality for intersection:
        # If one ends exactly where the next starts, it's not an intersection.
        return not (bb1['max_x'] <= bb2['min_x'] or
                   bb1['min_x'] >= bb2['max_x'] or
                   bb1['max_y'] <= bb2['min_y'] or
                   bb1['min_y'] >= bb2['max_y'])
