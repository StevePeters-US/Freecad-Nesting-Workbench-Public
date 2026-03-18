"""
Physics engine for the manual nesting tool.
Handles repulsion and falloff computation for parts near a dragged part.
This module is designed to be standalone and doesn't import FreeCAD.
"""

class PhysicsEngine:
    def __init__(self, radius=200.0, curve_exponent=2.0, strength=1.0):
        """
        Args:
            radius: max influence distance (mm) from dragged part center
            curve_exponent: falloff curve power (1=linear, 2=quadratic, 3=cubic)
            strength: global multiplier on displacement
        """
        self.radius = radius
        self.curve_exponent = curve_exponent
        self.strength = strength

    def compute_falloff(self, distance):
        """Returns falloff factor in [0, 1]. 0 = no influence, 1 = full influence."""
        if distance >= self.radius:
            return 0.0
        if distance <= 0:
            return 1.0
        return max(0.0, 1.0 - (distance / self.radius) ** self.curve_exponent)

    def compute_displacements(self, dragged_center, dragged_width, dragged_height, drag_delta, parts_info):
        """
        Compute displacement vectors for all parts based on gap distance to dragged part.
        Parts are pushed AWAY from the dragged part center (repulsion).

        Args:
            dragged_center: FreeCAD.Vector — current center of the dragged part
            dragged_width: float — width of dragged part (X)
            dragged_height: float — height of dragged part (Y)
            drag_delta: FreeCAD.Vector — how much the dragged part moved this frame
            parts_info: list of (obj, center, width, height) — other parts

        Returns:
            list of (obj, FreeCAD.Vector) — each part and its displacement vector
        """
        displacements = []
        for obj, center, width, height in parts_info:
            # Calculate center-to-center distance
            dx = center.x - dragged_center.x
            dy = center.y - dragged_center.y
            center_distance = (dx**2 + dy**2)**0.5

            if center_distance < 0.001:
                # Exactly at center? Random nudge or skip
                displacements.append((obj, type(drag_delta)(0, 0, 0)))
                continue

            # Edge-to-edge (gap) distance calculation
            # Subtract half-extents of both parts from the center-to-center components
            gap_x = max(0.0, abs(dx) - (dragged_width + width) / 2.0)
            gap_y = max(0.0, abs(dy) - (dragged_height + height) / 2.0)
            edge_distance = (gap_x**2 + gap_y**2)**0.5

            # Force falloff based on the gap distance
            factor = self.compute_falloff(edge_distance) * self.strength
            
            if factor < 0.001:
                displacements.append((obj, type(drag_delta)(0, 0, 0)))
                continue

            # Repulsion direction: always push away from dragged part center
            push_magnitude = drag_delta.Length * factor
            
            repulse_x = dx / center_distance * push_magnitude
            repulse_y = dy / center_distance * push_magnitude
            
            displacement_vec = type(drag_delta)(repulse_x, repulse_y, 0)
            displacements.append((obj, displacement_vec))
            
        return displacements
