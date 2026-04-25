import math

import threading

try:
    import taichi as ti
    import numpy as np
    from shapely.ops import unary_union
    TAICHI_AVAILABLE = True
except ImportError:
    TAICHI_AVAILABLE = False

# Track which backend Taichi was actually initialized with.
_taichi_arch = None  # e.g. 'vulkan', 'cuda', 'opengl', or 'cpu'

if TAICHI_AVAILABLE:
    # Initialize Taichi with Vulkan backend if available, fallback to others.
    # We prefer a real GPU backend; CPU is a last resort.
    for _arch_name, _arch in [
        ("vulkan", ti.vulkan),
        ("cuda", ti.cuda),
        ("opengl", ti.opengl),
        ("cpu", ti.cpu),
    ]:
        try:
            ti.init(arch=_arch)
            _taichi_arch = _arch_name
            break
        except Exception:
            continue

    if _taichi_arch:
        import FreeCAD
        FreeCAD.Console.PrintMessage(
            f"[nfp_gpu_taichi] Taichi initialized with backend: {_taichi_arch}\n"
        )
    else:
        TAICHI_AVAILABLE = False

# Global lock to prevent concurrent Taichi kernel launches from multiple threads.
_kernel_lock = threading.Lock()

def is_available():
    """Returns True only when Taichi is running on a real GPU backend."""
    return TAICHI_AVAILABLE and _taichi_arch not in (None, "cpu")

def get_backend():
    """Returns the name of the active Taichi backend, or None if unavailable."""
    return _taichi_arch if TAICHI_AVAILABLE else None

# Max vertices for convex hulls computed on GPU.
MAX_HULL_VERTS = 128

if TAICHI_AVAILABLE:
    @ti.kernel
    def compute_nfp_pairs_kernel(
        n_pairs: int,
        arr_a: ti.types.ndarray(),  # [n_pairs, max_verts_a, 2]
        len_a: ti.types.ndarray(),  # [n_pairs]
        arr_b: ti.types.ndarray(),  # [n_pairs, max_verts_b, 2]
        len_b: ti.types.ndarray(),  # [n_pairs]
        rotations: ti.types.ndarray(), # [n_pairs]
        out_vertices: ti.types.ndarray(), # [n_pairs, max_verts_out, 2]
        out_len: ti.types.ndarray() # [n_pairs]
    ):
        """
        Computes Minkowski sums for arbitrary pairs of convex polygons.
        """
        for p in range(n_pairs):
            angle = rotations[p]
            c = ti.cos(angle)
            s = ti.sin(angle)
            
            count_a = len_a[p]
            count_b = len_b[p]
            
            out_idx = 0
            for va_idx in range(count_a):
                ax = arr_a[p, va_idx, 0]
                ay = arr_a[p, va_idx, 1]
                
                for vb_idx in range(count_b):
                    bx_raw = arr_b[p, vb_idx, 0]
                    by_raw = arr_b[p, vb_idx, 1]
                    
                    # Rotate B
                    bx = bx_raw * c - by_raw * s
                    by = bx_raw * s + by_raw * c
                    
                    out_vertices[p, out_idx, 0] = ax + bx
                    out_vertices[p, out_idx, 1] = ay + by
                    out_idx += 1
            out_len[p] = out_idx

    @ti.kernel
    def compute_minkowski_sum_convex_kernel(
        n_poly_a: int, 
        n_poly_b: int,
        n_rotations: int,
        arr_a: ti.types.ndarray(),  # Flattened vertices of A: [n_poly_a, max_verts_a, 2]
        len_a: ti.types.ndarray(),  # Vertex count for each A: [n_poly_a]
        arr_b: ti.types.ndarray(),  # Flattened vertices of B: [n_poly_b, max_verts_b, 2]
        len_b: ti.types.ndarray(),  # Vertex count for each B: [n_poly_b]
        rotations: ti.types.ndarray(), # Rotation angles in radians: [n_rotations]
        out_vertices: ti.types.ndarray(), # Output: [n_rotations, n_poly_a, n_poly_b, max_verts_out, 2]
        out_len: ti.types.ndarray() # Output counts: [n_rotations, n_poly_a, n_poly_b]
    ):
        """
        Computes the Minkowski Sum of convex polygons A and B for multiple rotations.
        This simple version implements the "brute force sum of vertices" approach for convex polygons,
        generating the Convex Hull of {v_a + v_b_rotated}.
        
        LIMITATION: This kernel computes ALL pairwise sums. The Convex Hull step is easier done on CPU 
        or a separate kernel because reduced hull algorithms are complex to parallelize per-thread.
        So, this kernel outputs ALL combinations of vertices v_a + v_b.
        The CPU will then compute the Convex Hull of these points to get the final NFP.
        
        Actually, for two convex polygons P and Q, the Minkowski sum P + Q is the convex hull 
        of {p_i + q_j} for all vertices.
        """
        
        # Parallelize over rotations, poly_a, and poly_b
        for r, i, j in ti.ndrange(n_rotations, n_poly_a, n_poly_b):
            angle = rotations[r]
            c = ti.cos(angle)
            s = ti.sin(angle)
            
            count_a = len_a[i]
            count_b = len_b[j]
            
            # We simply output all pair sums. 
            # The number of output points is count_a * count_b
            # We need to make sure out_vertices is large enough.
            
            out_idx = 0
            for va_idx in range(count_a):
                ax = arr_a[i, va_idx, 0]
                ay = arr_a[i, va_idx, 1]
                
                for vb_idx in range(count_b):
                    # Rotate B vertices
                    bx_raw = arr_b[j, vb_idx, 0]
                    by_raw = arr_b[j, vb_idx, 1]
                    
                    bx = bx_raw * c - by_raw * s
                    by = bx_raw * s + by_raw * c
                    
                    # Sum
                    out_vertices[r, i, j, out_idx, 0] = ax + bx
                    out_vertices[r, i, j, out_idx, 1] = ay + by
                    out_idx += 1
                    
            out_len[r, i, j] = out_idx

    @ti.kernel
    def is_inside_any_convex_kernel(
        n_points: int,
        points: ti.types.ndarray(),        # [n_points, 2]
        n_polys: int,
        poly_starts: ti.types.ndarray(),   # [n_polys] start index in vertices array
        poly_lens: ti.types.ndarray(),     # [n_polys] number of vertices
        vertices: ti.types.ndarray(),      # [total_vertices, 2]
        results: ti.types.ndarray()        # [n_points] - 1 if inside any, 0 otherwise
    ):
        """
        Check if each point is inside any of the convex polygons in the batch.
        Parallelizes over points. For each point, iterate through polygons.
        Inside check for convex: point must be on the same side of all edges.
        """
        for p_idx in range(n_points):
            px = points[p_idx, 0]
            py = points[p_idx, 1]
            
            is_found = 0
            for poly_idx in range(n_polys):
                if is_found == 1:
                    continue
                
                start = poly_starts[poly_idx]
                count = poly_lens[poly_idx]
                
                if count < 3:
                    continue
                
                has_pos = 0
                has_neg = 0
                for i in range(count):
                    # Edge from V_i to V_{i+1}
                    v1x = vertices[start + i, 0]
                    v1y = vertices[start + i, 1]
                    
                    next_idx = i + 1
                    if next_idx == count:
                        next_idx = 0
                    
                    v2x = vertices[start + next_idx, 0]
                    v2y = vertices[start + next_idx, 1]
                    
                    # Cross product to determine side
                    # (v2.x - v1.x) * (p.y - v1.y) - (v2.y - v1.y) * (p.x - v1.x)
                    side = (v2x - v1x) * (py - v1y) - (v2y - v1y) * (px - v1x)
                    
                    if side > 1e-6:
                        has_pos = 1
                    elif side < -1e-6:
                        has_neg = 1
                    
                    # If we have both, it's outside a convex hull
                    if has_pos == 1 and has_neg == 1:
                        break
                
                if (has_pos == 1 and has_neg == 0) or (has_pos == 0 and has_neg == 1) or (has_pos == 0 and has_neg == 0):
                    is_found = 1
            
            results[p_idx] = is_found

    @ti.kernel
    def convex_hull_2d_kernel(
        n_pairs: int,
        points: ti.types.ndarray(),     # [n_pairs, max_pts, 2]  float32
        n_points: ti.types.ndarray(),   # [n_pairs]              int32
        hull_out: ti.types.ndarray(),   # [n_pairs, MAX_HULL_VERTS, 2]  float32
        hull_len: ti.types.ndarray(),   # [n_pairs]              int32
    ):
        """
        Computes the 2D convex hull of a point cloud for each pair using Jarvis March (Gift Wrapping).
        Parallelized over n_pairs.
        """
        for p in range(n_pairs):
            pts_count = n_points[p]
            if pts_count < 3:
                hull_len[p] = 0
                continue
            
            # If there's a tie, pick the one with the lowest y-coordinate.
            leftmost = 0
            for i in range(1, pts_count):
                if points[p, i, 0] < points[p, leftmost, 0]:
                    leftmost = i
                elif points[p, i, 0] == points[p, leftmost, 0]:
                    if points[p, i, 1] < points[p, leftmost, 1]:
                        leftmost = i
            
            curr = leftmost
            hull_idx = 0
            
            # Taichi doesn't allow infinite loops, so we use a bounded loop.
            # MAX_HULL_VERTS is used as a safety bound.
            for _h in range(MAX_HULL_VERTS):
                hull_out[p, hull_idx, 0] = points[p, curr, 0]
                hull_out[p, hull_idx, 1] = points[p, curr, 1]
                hull_idx += 1
                
                # Find the next point such that all other points are to the left of the edge (curr, next_pt).
                # We start by picking an arbitrary point (say 0, or (curr + 1) % pts_count).
                next_pt = (curr + 1) % pts_count
                
                for i in range(pts_count):
                    if i == curr:
                        continue
                    
                    # Cross product of (points[curr], points[next_pt], points[i])
                    # If (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x) > 0, 
                    # then p3 is to the left of p1->p2.
                    p1x, p1y = points[p, curr, 0], points[p, curr, 1]
                    p2x, p2y = points[p, next_pt, 0], points[p, next_pt, 1]
                    p3x, p3y = points[p, i, 0], points[p, i, 1]
                    
                    cp = (p2x - p1x) * (p3y - p1y) - (p2y - p1y) * (p3x - p1x)
                    
                    if cp > 1e-6:
                        next_pt = i
                    elif ti.abs(cp) < 1e-6:
                        # Collinear points: pick the one further from curr to keep the hull minimal but correct.
                        dist_sq_next = (p2x - p1x)**2 + (p2y - p1y)**2
                        dist_sq_i = (p3x - p1x)**2 + (p3y - p1y)**2
                        if dist_sq_i > dist_sq_next:
                            next_pt = i
                
                curr = next_pt
                
                # If we're back at the start, the hull is complete.
                if curr == leftmost:
                    break
                
                # Safety break if we exceed MAX_HULL_VERTS
                if hull_idx >= MAX_HULL_VERTS:
                    break
            
            hull_len[p] = hull_idx

    def compute_convex_hulls_gpu(points_np, n_points_np):
        """
        GPU-accelerated convex hull computation for a batch of point clouds.
        Returns a list of shapely.Polygon objects.
        """
        from shapely.geometry import Polygon
        
        n_pairs = len(n_points_np)
        if n_pairs == 0:
            return []
            
        max_pts = points_np.shape[1]
        
        hull_out_np = np.zeros((n_pairs, MAX_HULL_VERTS, 2), dtype=np.float32)
        hull_len_np = np.zeros(n_pairs, dtype=np.int32)
        
        with _kernel_lock:
            convex_hull_2d_kernel(
                n_pairs,
                points_np,
                n_points_np,
                hull_out_np,
                hull_len_np
            )
            
        results = []
        for i in range(n_pairs):
            count = hull_len_np[i]
            if count < 3:
                results.append(None)
                continue
            
            # Build polygon from hull vertices
            hull_vertices = hull_out_np[i, :count]
            results.append(Polygon(hull_vertices))
            
        return results

    @ti.kernel
    def bounds_check_kernel(
        n_pts: int,
        points: ti.types.ndarray(),          # [n_pts, 2]  float32 — candidate centroids
        rotated_extents: ti.types.ndarray(), # [n_pts, 4]  float32 — [min_x, min_y, max_x, max_y] per candidate relative to its centroid
        bin_w: float,
        bin_h: float,
        results: ti.types.ndarray(),         # [n_pts]  int32 — 1=in-bounds, 0=out
    ):
        """
        Check if each candidate (represented by centroid + rotated relative bounds) 
        fits inside the rectangular bin [0, bin_w] x [0, bin_h].
        """
        for i in range(n_pts):
            px = points[i, 0]
            py = points[i, 1]
            # Extents are relative to centroid
            min_x = rotated_extents[i, 0]
            min_y = rotated_extents[i, 1]
            max_x = rotated_extents[i, 2]
            max_y = rotated_extents[i, 3]
            
            if (px + min_x >= -1e-5 and px + max_x <= bin_w + 1e-5 and 
                py + min_y >= -1e-5 and py + max_y <= bin_h + 1e-5):
                results[i] = 1
            else:
                results[i] = 0

    def compute_batch_pip(points_np, convex_polys):
        """
        Efficiently check if a list of points are inside ANY of the provided convex polygons.
        Returns a numpy array of 1s (inside) and 0s (outside).
        """
        if not points_np.any() or not convex_polys:
            return np.zeros(len(points_np), dtype=np.int32)
            
        n_points = len(points_np)
        n_polys = len(convex_polys)
        
        # Flatten polygons into a single array for the kernel
        poly_lens = np.array([len(p.exterior.coords) - 1 for p in convex_polys], dtype=np.int32)
        poly_starts = np.zeros(n_polys, dtype=np.int32)
        total_verts = sum(poly_lens)
        
        all_vertices = np.zeros((total_verts, 2), dtype=np.float32)
        current_offset = 0
        for i, p in enumerate(convex_polys):
            poly_starts[i] = current_offset
            coords = np.array(p.exterior.coords)[:-1]
            all_vertices[current_offset:current_offset + poly_lens[i]] = coords
            current_offset += poly_lens[i]
            
        results_np = np.zeros(n_points, dtype=np.int32)
        
        with _kernel_lock:
            is_inside_any_convex_kernel(
                n_points, points_np,
                n_polys, poly_starts, poly_lens, all_vertices,
                results_np
            )
            
        return results_np

    def compute_batch_pip_with_holes(points_np, solid_polys, hole_polys):
        """
        Check if points are inside SOLID polygons AND NOT inside any HOLE polygons.
        Provides exact NFP collision scoring without any CPU-side union.
        """
        if not points_np.any():
            return np.zeros(len(points_np), dtype=np.int32)
            
        solid_results = compute_batch_pip(points_np, solid_polys)
        if not np.any(solid_results == 1):
            return solid_results # All 0
            
        if not hole_polys:
            return solid_results
            
        hole_results = compute_batch_pip(points_np, hole_polys)
        
        return solid_results & ~hole_results

    def compute_nfp_pairs(pairs):
        """
        Computes Minkowski sums for arbitrary pairs of convex polygons.
        Each pair is (poly_a, poly_b, rotation_rad).
        """
        from shapely.geometry import MultiPoint
        if not pairs:
            return []
            
        n_pairs = len(pairs)
        max_v_a = max(len(p[0].exterior.coords) for p in pairs)
        max_v_b = max(len(p[1].exterior.coords) for p in pairs)
        max_out_verts = max_v_a * max_v_b
        
        np_a = np.zeros((n_pairs, max_v_a, 2), dtype=np.float32)
        len_a = np.zeros(n_pairs, dtype=np.int32)
        np_b = np.zeros((n_pairs, max_v_b, 2), dtype=np.float32)
        len_b = np.zeros(n_pairs, dtype=np.int32)
        np_rot = np.zeros(n_pairs, dtype=np.float32)
        
        for i, (p_a, p_b, rot) in enumerate(pairs):
            coords_a = np.array(p_a.exterior.coords)[:-1]
            np_a[i, :len(coords_a)] = coords_a
            len_a[i] = len(coords_a)
            
            # Note: For NFP, we technically want A + (-B). 
            # We assume the caller passed the -B version if they wanted NFP.
            coords_b = np.array(p_b.exterior.coords)[:-1]
            np_b[i, :len(coords_b)] = coords_b
            len_b[i] = len(coords_b)
            np_rot[i] = rot
            
        out_verts_np = np.zeros((n_pairs, max_out_verts, 2), dtype=np.float32)
        out_len_np = np.zeros(n_pairs, dtype=np.int32)
        
        with _kernel_lock:
            compute_nfp_pairs_kernel(
                n_pairs,
                np_a, len_a,
                np_b, len_b,
                np_rot,
                out_verts_np,
                out_len_np
            )
            
        # GPU Convex Hull (GPU-001)
        return compute_convex_hulls_gpu(out_verts_np, out_len_np)

    def compute_nfp_batch(poly_a_list, poly_b_list, rotations_deg):
        """
        Computes the NFP for a list of convex polygons A and B across multiple rotations.
        
        Args:
            poly_a_list: List of shapely.Polygon (convex parts of A)
            poly_b_list: List of shapely.Polygon (convex parts of B)
            rotations_deg: List of rotation angles in degrees
            
        Returns:
            A list of results per rotation. Each result is a list of shapely.Polygon (the convex NFPs).
        """
        from shapely.geometry import Polygon, MultiPoint
        
        n_a = len(poly_a_list)
        n_b = len(poly_b_list)
        n_r = len(rotations_deg)
        
        # max vertices to pad arrays
        # Note: For NFP, strictly speaking we computing A + (-B).
        # So we assume the caller has already negated B or we handle it?
        # Standard Minkowski Sum is A + B. NFP(A,B) ~ A + (-B).
        # We will assume standard sum here and let the caller input -B if needed.
        
        max_v_a = max(len(p.exterior.coords) for p in poly_a_list)
        max_v_b = max(len(p.exterior.coords) for p in poly_b_list)
        
        # Pre-allocate numpy arrays
        np_a = np.zeros((n_a, max_v_a, 2), dtype=np.float32)
        len_a = np.zeros(n_a, dtype=np.int32)
        
        np_b = np.zeros((n_b, max_v_b, 2), dtype=np.float32)
        len_b = np.zeros(n_b, dtype=np.int32)
        
        for i, p in enumerate(poly_a_list):
            coords = np.array(p.exterior.coords)[:-1] # Drop duplicate end point
            c_len = len(coords)
            np_a[i, :c_len] = coords
            len_a[i] = c_len
            
        for i, p in enumerate(poly_b_list):
            coords = np.array(p.exterior.coords)[:-1]
            c_len = len(coords)
            np_b[i, :c_len] = coords
            len_b[i] = c_len
            
        np_rot = np.radians(np.array(rotations_deg, dtype=np.float32))
        
        # Output size: In worst case (brute force sum), we have V_a * V_b points.
        # Convex hull will reduce this significantly later.
        max_out_verts = max_v_a * max_v_b
        
        # Allocate fields
        # Creating fields every call might be slow. In production, we should cache fields 
        # or use dynamic SNode if sizes vary wildly. For now, simple ndarray.
        
        # Note: Taichi ndarray interacting with numpy is fast.
        
        out_verts_np = np.zeros((n_r, n_a, n_b, max_out_verts, 2), dtype=np.float32)
        out_len_np = np.zeros((n_r, n_a, n_b), dtype=np.int32)
        
        # Call Kernel (protected by lock)
        with _kernel_lock:
            compute_minkowski_sum_convex_kernel(
                n_a, n_b, n_r, 
                np_a, 
                len_a, 
                np_b, 
                len_b, 
                np_rot, 
                out_verts_np, 
                out_len_np
            )
        
        # GPU Convex Hull (GPU-001)
        # Flatten (n_r, n_a, n_b) into (n_r * n_a * n_b) for compute_convex_hulls_gpu
        total_minkowski_pairs = n_r * n_a * n_b
        flat_out_verts = out_verts_np.reshape((total_minkowski_pairs, max_out_verts, 2))
        flat_out_len = out_len_np.reshape(total_minkowski_pairs)
        
        flat_hulls = compute_convex_hulls_gpu(flat_out_verts, flat_out_len)
        
        # Reshape results back to per-rotation lists
        results_per_rotation = []
        hull_idx = 0
        for r in range(n_r):
            minkowski_polys = []
            for i in range(n_a):
                for j in range(n_b):
                    hull = flat_hulls[hull_idx]
                    if hull:
                        minkowski_polys.append(hull)
                    hull_idx += 1
            results_per_rotation.append(minkowski_polys)
            
        return results_per_rotation

else:
    def compute_nfp_batch(poly_a_list, poly_b_list, rotations_deg):
        raise ImportError("Taichi is not installed. Cannot compute GPU NFP.")

    def bounds_check_kernel(n_pts, points, rotated_extents, bin_w, bin_h, results):
        raise ImportError("Taichi is not installed. Cannot compute GPU bounds check.")
