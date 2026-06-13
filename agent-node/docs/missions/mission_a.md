# Mission A — P0.1(a): Self-Assembly into Commanded Truss Shape

## 1. Mission Overview

Task P0.1(a) validates the swarm's ability to transition from an arbitrary, unconnected initial configuration to a specified truss topology entirely through autonomous inter-module coordination. A goal vector **g** encoding the target adjacency matrix and node centroid positions is injected at t = 0. The 20-module swarm (12 struts, 8 nodes) must then negotiate docking sequences, resolve connector polarity, and achieve a fully connected graph isomorphic to the commanded structure—without human intervention and without safety violations. This mission is the foundational self-assembly benchmark: it exercises the full P0.1 pipeline (perception → planning → motion → docking) against a ground-truth structural target and provides the baseline pass/fail signal used to gate all downstream manipulation and locomotion tasks.

---

## 2. Initial Conditions

**Module layout at t = 0:**

- All 20 modules are placed on the hard flat surface in a **scattered, fully disconnected** configuration (no existing docking connections).
- Modules are distributed within a 1.5 m × 1.5 m floor zone, minimum inter-module clearance 50 mm (edge to edge), such that no module initially satisfies any adjacency constraint of the target graph.
- Strut modules (×12): long axis oriented randomly in the horizontal plane; each strut rests on its two end-cap feet. Strut length 220 mm, resting footprint ~220 mm × 40 mm.
- Node modules (×8): resting on flat base face, connector ports facing outward, diameter 90 mm.
- All docking latches are in the **open/disengaged** state.
- All modules are individually powered on; onboard state machines are in `IDLE`.

**Goal vector injection:**

- Goal vector **g** = { A_target ∈ {0,1}^{20×20}, P_target ∈ ℝ^{8×3} } is broadcast over the IR Layer 1 mesh by the orchestrator at t = 0 ms.
- A_target encodes the commanded adjacency matrix (symmetric, zero diagonal) for the target truss.
- P_target encodes the 3-D centroid positions of the 8 node modules in the assembled configuration, expressed in the arena reference frame (origin at arena SW corner, z up).
- Strut endpoint positions are fully determined by P_target and A_target; they are not independently specified in **g**.

**Environment state at t = 0:**

- Ambient temperature within 10–35 °C.
- Floor surface: hard, flat, level to ±2 mm over the arena footprint.
- No obstacles other than swarm modules.
- IR and ESP-NOW communication channels clear (no competing traffic).

---

## 3. Success Predicate

**English definition:**

The mission is successful if and only if, at or before the time limit T_max:

1. The swarm forms a single connected graph (no isolated modules or sub-clusters).
2. The realized adjacency matrix A_actual matches A_target exactly (no missing edges, no spurious edges).
3. Each node module centroid is within ±30 mm of its corresponding target position in P_target (Euclidean distance in the horizontal plane; vertical offset ≤ 10 mm).
4. All docking latches at edges present in A_target report `LATCHED` state.
5. No safety violation (e-stop trigger, collision fault, thermal fault, or communication blackout > 2 s) occurred at any point during execution.

**Pseudocode:**

```python
def check_assembly_success(state, g, t_elapsed, T_max, safety_log):
    if t_elapsed > T_max:
        return False                          # time limit exceeded

    A_target = g["adjacency"]                # shape (20, 20), dtype bool
    P_target = g["node_positions"]           # shape (8, 3), metres

    # Condition 1 & 2: graph topology
    A_actual = state.get_adjacency_matrix()  # from latch telemetry
    if not np.array_equal(A_actual, A_target):
        return False

    # Condition 1 (connectivity): A_target must already be connected by design,
    # but verify realised graph is connected
    if not is_connected(A_actual):
        return False

    # Condition 3: node centroid positions
    node_positions_actual = state.get_node_centroids()  # shape (8, 3)
    for i in range(8):
        xy_err = np.linalg.norm(node_positions_actual[i, :2] - P_target[i, :2])
        z_err  = abs(node_positions_actual[i, 2] - P_target[i, 2])
        if xy_err > 0.030 or z_err > 0.010:
            return False

    # Condition 4: all target-edge latches locked
    for (u, v) in np.argwhere(A_target):
        if state.latch_state(u, v) != LATCHED:
            return False

    # Condition 5: no safety violations
    if safety_log.any_violation():
        return False

    return True
```

See `predicates.py`: `check_assembly_success()`

---

## 4. Time Limit

**T_max = 300 s (5 minutes)**

**Justification:**

The P0.4 latency budget allocates ≤ 10 s from instruction receipt to swarm activation. The remaining time budget is derived as follows:

| Phase | Allocation |
|---|---|
| Goal vector broadcast + module parse | ≤ 2 s |
| Distributed planning (role assignment, path negotiation) | ≤ 15 s |
| Motion to docking proximity (worst-case 20 modules × traversal) | ≤ 200 s |
| Sequential docking handshakes (up to 19 edges in a spanning tree) | ≤ 57 s |
| Final position verification + latch confirmation | ≤ 26 s |
| **Total** | **≤ 300 s** |

With max collective speed 0.3 m/s and a worst-case travel distance of ~1.5 m per module, per-module traversal is bounded at ~5 s; with 20 modules operating in parallel, the motion phase is dominated by serialized docking handshakes rather than transit. The 300 s limit provides a ×1.4 margin over the nominal path estimate of ~215 s. Endurance margins are not binding: struts carry ≥ 30 min and nodes ≥ 60 min of battery, both exceeding T_max.

---

## 5. Environment Assumptions

**Inherited from P0.3:**

- Indoor operation; no direct sunlight on modules.
- Hard, flat, continuous surface (concrete, tile, or equivalent); friction coefficient μ ≥ 0.3.
- Ambient temperature 10–35 °C.
- Relative humidity ≤ 80 % non-condensing.
- Ingress protection: IP40 (no protection against liquids; no significant dust).
- No electromagnetic interference sources within 2 m that occupy the 2.4 GHz or IR communication bands at power levels exceeding the module link budget.

**Task-specific additions:**

- The 1.5 m × 1.5 m arena floor is free of debris ≥ 5 mm in any dimension.
- No external airflow exceeding 0.5 m/s (fans, HVAC vents) within the arena footprint that could perturb resting modules.
- Arena boundary is marked but not physically walled; modules must not exit the 2 m × 2 m safety perimeter (enforced by geofence in the controller).
- Overhead localization system (UWB anchors or equivalent) is calibrated and operational before t = 0; positional fix accuracy ≤ 15 mm (1σ) for all modules throughout the run.
- The goal vector **g** is validated (A_target is connected, realizable with the given module count, and P_target fits within the arena) before broadcast; invalid goal vectors are a pre-mission fault, not a runtime failure mode.

---

## 6. Failure Modes

Each condition below maps to `check_assembly_success()` returning `False` or to a mission abort.

| ID | Failure Condition | Predicate Effect |
|---|---|---|
| F-01 | Time limit T_max exceeded before all success conditions met | `t_elapsed > T_max` → `False` |
| F-02 | One or more modules isolated (disconnected subgraph) at T_max | `is_connected(A_actual) == False` → `False` |
| F-03 | Realized adjacency matrix differs from A_target (missing or spurious edge) | `A_actual != A_target` → `False` |
| F-04 | Any node centroid outside ±30 mm horizontal or ±10 mm vertical tolerance | position check loop → `False` |
| F-05 | One or more target-edge latches not in `LATCHED` state | latch state check → `False` |
| F-06 | E-stop triggered (any module, any cause) during execution | `safety_log.any_violation()` → `False`; mission abort |
| F-07 | Inter-module collision detected (contact force > threshold) | logged as safety violation → `False`; mission abort |
| F-08 | Module thermal fault (onboard temp > operating limit) | logged as safety violation → `False`; mission abort |
| F-09 | Communication blackout > 2 s (module unreachable on both IR + ESP-NOW) | logged as safety violation → `False`; mission abort |
| F-10 | Module exits 2 m × 2 m geofence perimeter | geofence fault → mission abort |
| F-11 | Battery low-cutoff reached on any module before T_max (strut < 30 min endurance) | mission abort; flags hardware fault |
| F-12 | Localization fix lost > 5 s for any module during active motion phase | mission abort; flags sensor fault |

---

## 7. Scenario Role

Mission A is the entry point for the §2.6 scenario suite and the first task in the §3.4 curriculum. It isolates pure self-assembly performance from locomotion and manipulation complexity, making it the canonical Stage C3 ("static truss formation from scatter") benchmark. Passing Mission A gates progression to C4 (assembly from partial pre-connection), C5 (assembly under obstacle perturbation), and C6 (dynamic re-assembly after partial disassembly). The pass/fail signal and the per-run telemetry—docking event timestamps, path traces, planning latency, latch retry counts—feed the curriculum's difficulty-progression controller: if the pass rate over a rolling window of N runs exceeds the C3 threshold, the controller promotes to C4 and injects a harder goal vector drawn from the §2.6 target library. Mission A data also calibrates the position-tolerance and timing parameters used in the success predicates of all downstream missions; if systematic centroid error is observed here, the localization pipeline is corrected before those missions run.

---

## 8. Notes / Open Items

- **NI-01 (goal vector schema):** The format of **g** (adjacency matrix encoding, endianness, frame convention for P_target) must be finalized and frozen before the first hardware run. Current assumption is row-major uint8 packed adjacency matrix + float32 XYZ array, little-endian, broadcast as a single IR Layer 1 packet. If the packet exceeds the IR MTU, fragmentation logic must be specified.

- **NI-02 (docking handshake ordering):** The distributed algorithm for negotiating which module docks first (to avoid deadlock when two modules simultaneously approach the same connector port) is not yet specified. A token-passing or priority-ID scheme is needed; this affects the F-02/F-03 failure rate significantly.

- **NI-03 (localization during docking):** When two modules are within ~30 mm of each other, UWB multipath may degrade fix accuracy below the 15 mm budget. Evaluate whether IR proximity sensors or connector-face capacitive sensing can substitute for localization during the final approach phase.

- **NI-04 (floor friction variability):** The μ ≥ 0.3 assumption has not been validated for all candidate indoor surfaces. A sweep test across tile, sealed concrete, and rubber mat is needed before P0.3 environment specs are signed off.

- **NI-05 (goal vector validation gate):** `predicates.py` currently does not implement the pre-mission validity check for **g** (see §5). This must be added before integration testing to prevent wasted runs on structurally infeasible targets.

- **NI-06 (partial-success metric):** The binary success predicate does not capture near-miss performance (e.g., 19/20 modules correctly placed). A continuous assembly-completeness score (fraction of edges correct, mean centroid error) should be logged alongside the binary result to support curriculum difficulty tuning.
