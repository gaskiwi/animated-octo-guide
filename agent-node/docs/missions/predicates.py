"""
Mission success predicates for the FreeSN-derived swarm prototype.

20-module configuration: 12 struts + 8 nodes (P0.1, master plan §3.2).
Each predicate returns True iff all success conditions are simultaneously met.
"""

import math
import sys
import numpy as np


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def is_graph_connected(adjacency_matrix) -> bool:
    """Return True iff the undirected graph described by adjacency_matrix is connected.

    Uses iterative union-find (path compression + union by rank).

    Parameters
    ----------
    adjacency_matrix : NxN array-like of 0/1
    """
    adj = np.asarray(adjacency_matrix, dtype=int)
    n = adj.shape[0]
    if n == 0:
        return True

    parent = list(range(n))
    rank = [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    for i in range(n):
        for j in range(i + 1, n):
            if adj[i, j]:
                union(i, j)

    root = find(0)
    return all(find(i) == root for i in range(1, n))


# ---------------------------------------------------------------------------
# Predicate 1 — assembly
# ---------------------------------------------------------------------------

def check_assembly_success(
    state,
    target_adjacency,
    position_tolerance=0.030,
    target_positions=None,
    time_elapsed=None,
    time_limit=None,
    safety_violated=False,
) -> bool:
    """Return True iff the assembled structure matches the target configuration.

    Checks (all must pass):
    1. Safety not violated.
    2. Current adjacency matrix exactly matches target (0/1 values).
    3. Resulting graph is connected.
    4. Each node centroid within *position_tolerance* metres of its commanded
       position (only when *target_positions* is provided).
    5. time_elapsed <= time_limit (only when both are provided).

    Parameters
    ----------
    state : dict
        'node_positions'  : list of [x,y,z] for each node (metres)
        'adjacency_matrix': NxN array-like (current connections)
        'module_count'    : int
    target_adjacency : NxN array-like
        Desired connectivity (0/1).
    position_tolerance : float
        Maximum allowed Euclidean distance per node (metres).
    target_positions : list of [x,y,z] or None
        Commanded node positions; skip positional check when None.
    time_elapsed : float or None
        Seconds since task start.
    time_limit : float or None
        Maximum allowed seconds.
    safety_violated : bool
        Hard-stop flag from the safety monitor.
    """
    if safety_violated:
        return False

    if time_elapsed is not None and time_limit is not None:
        if time_elapsed > time_limit:
            return False

    current = np.asarray(state["adjacency_matrix"], dtype=int)
    target = np.asarray(target_adjacency, dtype=int)

    if current.shape != target.shape:
        return False
    if not np.array_equal(current, target):
        return False

    if not is_graph_connected(current):
        return False

    if target_positions is not None:
        node_positions = state["node_positions"]
        if len(node_positions) != len(target_positions):
            return False
        for pos, tgt in zip(node_positions, target_positions):
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, tgt)))
            if dist > position_tolerance:
                return False

    return True


# ---------------------------------------------------------------------------
# Predicate 2 — obstacle crossing
# ---------------------------------------------------------------------------

def check_obstacle_crossing_success(
    state,
    obstacle_far_boundary_x,
    position_tolerance=0.050,
    time_elapsed=None,
    time_limit=None,
    safety_violated=False,
) -> bool:
    """Return True iff the swarm has fully crossed the obstacle field.

    Checks (all must pass):
    1. Safety not violated.
    2. Swarm centroid x > obstacle_far_boundary_x.
    3. Every module x > obstacle_far_boundary_x - position_tolerance.
    4. Graph is connected (via union-find or state['swarm_connected']).
    5. time_elapsed <= time_limit (when both provided).

    Parameters
    ----------
    state : dict
        'module_positions' : list of [x,y,z] for all 20 modules
        'adjacency_matrix' : 20x20 array-like
        'swarm_connected'  : bool (may be used as fast path)
    obstacle_far_boundary_x : float
        x-coordinate of the far side of the obstacle field.
    position_tolerance : float
        Positional tolerance for the trailing-edge check (metres).
    time_elapsed : float or None
    time_limit : float or None
    safety_violated : bool
    """
    if safety_violated:
        return False

    if time_elapsed is not None and time_limit is not None:
        if time_elapsed > time_limit:
            return False

    positions = state["module_positions"]
    xs = [p[0] for p in positions]

    centroid_x = sum(xs) / len(xs)
    if centroid_x <= obstacle_far_boundary_x:
        return False

    trailing_limit = obstacle_far_boundary_x - position_tolerance
    if any(x <= trailing_limit for x in xs):
        return False

    # Prefer explicit flag; fall back to union-find
    connected = state.get("swarm_connected")
    if connected is None:
        connected = is_graph_connected(state["adjacency_matrix"])
    if not connected:
        return False

    return True


# ---------------------------------------------------------------------------
# Predicate 3 — transport
# ---------------------------------------------------------------------------

def check_transport_success(
    state,
    target_zone_center,
    target_zone_radius=0.050,
    payload_velocity_threshold=0.02,
    stationary_duration=1.0,
    min_struts_attached=2,
    time_elapsed=None,
    time_limit=None,
    safety_violated=False,
) -> bool:
    """Return True iff the payload has been successfully transported to the target zone.

    Checks (all must pass):
    1. Safety not violated.
    2. Payload 2-D position (x,y) within *target_zone_radius* of target centre.
    3. Payload speed below *payload_velocity_threshold* m/s.
    4. Payload has been stationary for >= *stationary_duration* seconds.
    5. At least *min_struts_attached* struts remain attached to the payload.
    6. Payload orientation error < 45°.
    7. time_elapsed <= time_limit (when both provided).

    Parameters
    ----------
    state : dict
        'payload_position'            : [x,y,z] (metres)
        'payload_velocity'            : float (m/s, scalar speed)
        'payload_stationary_duration' : float (seconds continuously stationary)
        'struts_attached_to_payload'  : int
        'payload_orientation_error'   : float (degrees)
    target_zone_center : [x,y,z]
    target_zone_radius : float  (metres, 2-D XY check)
    payload_velocity_threshold : float  (m/s)
    stationary_duration : float  (seconds, minimum required)
    min_struts_attached : int
    time_elapsed : float or None
    time_limit : float or None
    safety_violated : bool
    """
    if safety_violated:
        return False

    if time_elapsed is not None and time_limit is not None:
        if time_elapsed > time_limit:
            return False

    pp = state["payload_position"]
    tc = target_zone_center
    dist_2d = math.sqrt((pp[0] - tc[0]) ** 2 + (pp[1] - tc[1]) ** 2)
    if dist_2d > target_zone_radius:
        return False

    if state["payload_velocity"] >= payload_velocity_threshold:
        return False

    if state["payload_stationary_duration"] < stationary_duration:
        return False

    if state["struts_attached_to_payload"] < min_struts_attached:
        return False

    if state["payload_orientation_error"] >= 45.0:
        return False

    return True


# ---------------------------------------------------------------------------
# Predicate 4 — manipulation
# ---------------------------------------------------------------------------

def check_manipulation_success(
    state,
    target_position,
    target_orientation_euler,
    position_tolerance=0.030,
    orientation_tolerance_deg=10.0,
    velocity_threshold=0.02,
    stationary_duration=1.0,
    workspace_bounds=None,
    time_elapsed=None,
    time_limit=None,
    safety_violated=False,
) -> bool:
    """Return True iff the manipulated object has reached its target pose.

    Checks (all must pass):
    1. Safety not violated.
    2. Object 3-D position within *position_tolerance* of *target_position*.
    3. Each Euler angle (roll, pitch, yaw) within *orientation_tolerance_deg*
       of the corresponding target angle (shortest-path difference).
    4. Object speed < *velocity_threshold* m/s.
    5. Object has been stationary for >= *stationary_duration* seconds.
    6. Object within *workspace_bounds* (when provided).
    7. time_elapsed <= time_limit (when both provided).

    Parameters
    ----------
    state : dict
        'object_position'           : [x,y,z] (metres)
        'object_orientation_euler'  : [roll,pitch,yaw] (degrees)
        'object_velocity'           : float (m/s)
        'object_stationary_duration': float (seconds)
    target_position : [x,y,z]
    target_orientation_euler : [roll,pitch,yaw] in degrees
    position_tolerance : float  (metres)
    orientation_tolerance_deg : float  (degrees per axis)
    velocity_threshold : float  (m/s)
    stationary_duration : float  (seconds)
    workspace_bounds : dict or None
        Keys: 'x_min','x_max','y_min','y_max'
    time_elapsed : float or None
    time_limit : float or None
    safety_violated : bool
    """
    if safety_violated:
        return False

    if time_elapsed is not None and time_limit is not None:
        if time_elapsed > time_limit:
            return False

    op = state["object_position"]
    pos_dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(op, target_position)))
    if pos_dist > position_tolerance:
        return False

    oe = state["object_orientation_euler"]
    te = target_orientation_euler
    for current_angle, target_angle in zip(oe, te):
        diff = abs(current_angle - target_angle) % 360.0
        if diff > 180.0:
            diff = 360.0 - diff
        if diff > orientation_tolerance_deg:
            return False

    if state["object_velocity"] >= velocity_threshold:
        return False

    if state["object_stationary_duration"] < stationary_duration:
        return False

    if workspace_bounds is not None:
        x, y = op[0], op[1]
        if not (workspace_bounds["x_min"] <= x <= workspace_bounds["x_max"]):
            return False
        if not (workspace_bounds["y_min"] <= y <= workspace_bounds["y_max"]):
            return False

    return True


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    failures = 0

    def _check(label, result, expected):
        global failures
        ok = result == expected
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {label}")
        if not ok:
            failures += 1

    # --- is_graph_connected ---
    _check(
        "is_graph_connected: simple chain [0-1-2]",
        is_graph_connected([[0, 1, 0], [1, 0, 1], [0, 1, 0]]),
        True,
    )
    _check(
        "is_graph_connected: disconnected [0-1  2]",
        is_graph_connected([[0, 1, 0], [1, 0, 0], [0, 0, 0]]),
        False,
    )

    # --- check_assembly_success ---
    adj_3 = [[0, 1, 0], [1, 0, 1], [0, 1, 0]]
    state_asm = {
        "node_positions": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        "adjacency_matrix": adj_3,
        "module_count": 3,
    }
    _check(
        "assembly: TRUE (matches, connected, in tolerance)",
        check_assembly_success(
            state_asm, adj_3,
            target_positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        ),
        True,
    )
    _check(
        "assembly: FALSE (safety_violated)",
        check_assembly_success(state_asm, adj_3, safety_violated=True),
        False,
    )
    _check(
        "assembly: FALSE (adjacency mismatch)",
        check_assembly_success(
            state_asm,
            [[0, 1, 1], [1, 0, 1], [1, 1, 0]],
        ),
        False,
    )
    _check(
        "assembly: FALSE (position out of tolerance)",
        check_assembly_success(
            state_asm, adj_3,
            target_positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.10, 0.0, 0.0]],
            position_tolerance=0.030,
        ),
        False,
    )
    _check(
        "assembly: FALSE (time exceeded)",
        check_assembly_success(state_asm, adj_3, time_elapsed=11.0, time_limit=10.0),
        False,
    )

    # --- check_obstacle_crossing_success ---
    positions_20 = [[5.0 + i * 0.1, 0.0, 0.0] for i in range(20)]
    adj_20_chain = [[0] * 20 for _ in range(20)]
    for i in range(19):
        adj_20_chain[i][i + 1] = 1
        adj_20_chain[i + 1][i] = 1

    state_obs = {
        "module_positions": positions_20,
        "adjacency_matrix": adj_20_chain,
        "swarm_connected": True,
    }
    _check(
        "obstacle: TRUE (centroid=5.95, limit=5.0)",
        check_obstacle_crossing_success(state_obs, obstacle_far_boundary_x=4.9),
        True,
    )
    _check(
        "obstacle: FALSE (centroid behind boundary)",
        check_obstacle_crossing_success(state_obs, obstacle_far_boundary_x=6.5),
        False,
    )
    _check(
        "obstacle: FALSE (disconnected)",
        check_obstacle_crossing_success(
            {**state_obs, "swarm_connected": False,
             "adjacency_matrix": [[0] * 20 for _ in range(20)]},
            obstacle_far_boundary_x=4.9,
        ),
        False,
    )
    _check(
        "obstacle: FALSE (safety_violated)",
        check_obstacle_crossing_success(state_obs, 4.9, safety_violated=True),
        False,
    )

    # --- check_transport_success ---
    state_transport_ok = {
        "payload_position": [1.0, 1.0, 0.0],
        "payload_velocity": 0.005,
        "payload_stationary_duration": 2.0,
        "struts_attached_to_payload": 3,
        "payload_orientation_error": 10.0,
    }
    _check(
        "transport: TRUE",
        check_transport_success(state_transport_ok, target_zone_center=[1.0, 1.02, 0.0]),
        True,
    )
    _check(
        "transport: FALSE (outside zone)",
        check_transport_success(state_transport_ok, target_zone_center=[2.0, 2.0, 0.0]),
        False,
    )
    _check(
        "transport: FALSE (still moving)",
        check_transport_success(
            {**state_transport_ok, "payload_velocity": 0.10},
            target_zone_center=[1.0, 1.02, 0.0],
        ),
        False,
    )
    _check(
        "transport: FALSE (not stationary long enough)",
        check_transport_success(
            {**state_transport_ok, "payload_stationary_duration": 0.5},
            target_zone_center=[1.0, 1.02, 0.0],
        ),
        False,
    )
    _check(
        "transport: FALSE (orientation error >= 45°)",
        check_transport_success(
            {**state_transport_ok, "payload_orientation_error": 50.0},
            target_zone_center=[1.0, 1.02, 0.0],
        ),
        False,
    )

    # --- check_manipulation_success ---
    state_manip_ok = {
        "object_position": [0.01, 0.01, 0.0],
        "object_orientation_euler": [1.0, 2.0, 3.0],
        "object_velocity": 0.005,
        "object_stationary_duration": 2.0,
    }
    _check(
        "manipulation: TRUE",
        check_manipulation_success(
            state_manip_ok,
            target_position=[0.0, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
        ),
        True,
    )
    _check(
        "manipulation: FALSE (position out of tolerance)",
        check_manipulation_success(
            state_manip_ok,
            target_position=[0.10, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
        ),
        False,
    )
    _check(
        "manipulation: FALSE (orientation out of tolerance)",
        check_manipulation_success(
            {**state_manip_ok, "object_orientation_euler": [0.0, 0.0, 30.0]},
            target_position=[0.0, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
            orientation_tolerance_deg=10.0,
        ),
        False,
    )
    _check(
        "manipulation: FALSE (velocity too high)",
        check_manipulation_success(
            {**state_manip_ok, "object_velocity": 0.05},
            target_position=[0.0, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
        ),
        False,
    )
    _check(
        "manipulation: FALSE (outside workspace bounds)",
        check_manipulation_success(
            state_manip_ok,
            target_position=[0.0, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
            workspace_bounds={"x_min": 0.5, "x_max": 1.0, "y_min": 0.5, "y_max": 1.0},
        ),
        False,
    )
    _check(
        "manipulation: FALSE (safety_violated)",
        check_manipulation_success(
            state_manip_ok,
            target_position=[0.0, 0.0, 0.0],
            target_orientation_euler=[0.0, 0.0, 0.0],
            safety_violated=True,
        ),
        False,
    )

    print()
    if failures:
        print(f"{failures} test(s) FAILED.")
        sys.exit(1)
    else:
        print("All tests passed.")
        sys.exit(0)
