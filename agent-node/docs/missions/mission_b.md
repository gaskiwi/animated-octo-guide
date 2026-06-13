# mission_b.md — P0.1(b): Obstacle Crossing as a Connected Structure

## 1. Mission Overview

Task P0.1(b) requires the 20-module FreeSN swarm (12 struts, 8 nodes) to traverse a transverse obstacle field while maintaining structural connectivity throughout the entire crossing. The obstacle height (40–80 mm) exceeds the 30 mm single-module climbing limit, so the swarm cannot cross as independent units; instead it must reconfigure collectively — bridging, climbing, and flowing over the obstacle as a continuous graph — before reforming a stable locomotion gait on the far side. This scenario is the canonical test of connected-gait locomotion under geometric stress and is the primary validation scenario for swarm-level reconfiguration planning.

---

## 2. Initial Conditions

**World frame:** X-axis points in the direction of travel; Y-axis is lateral; Z-axis is up. The obstacle field occupies the X-interval [X_obs_enter, X_obs_exit] where X_obs_exit − X_obs_enter = 0.30 m (obstacle width). The swarm start zone is X < X_obs_enter; the goal zone is X > X_obs_exit.

**Obstacle geometry:**

| Parameter | Value |
|-----------|-------|
| Type | Uniform rectangular step or single row of flush-butted blocks |
| Height h_obs | 40–80 mm (sampled uniformly per trial; exact value recorded in trial metadata) |
| Width w_obs | 300 mm (X-direction depth) |
| Lateral extent | ≥ 600 mm (wider than the swarm's lateral footprint at maximum spread, ≈ 450 mm) |
| Surface | Hard, flat, non-compliant (concrete tile or equivalent); μ ≥ 0.5 |

**Swarm initial state:**

- All 20 modules assembled into a single connected graph (verified by connectivity check at t = 0).
- Swarm centroid C(0) is located at X_start = X_obs_enter − 0.20 m, with centroid Y within ±0.05 m of the obstacle centerline.
- All modules on the near-side surface (Z = 0), none overhanging the obstacle.
- All joint angles within nominal rest pose ±5°.
- Battery state: struts ≥ 30 min endurance remaining; nodes ≥ 60 min endurance remaining.

**Goal vector:**

```
g = (X_goal, Y_goal, tolerance)
  = (X_obs_exit + 0.20 m,  Y_center,  0.10 m)
```

The goal vector encodes the centroid waypoint on the far side. The mission is complete when the centroid reaches the cylinder of radius 0.10 m centered at g and all remaining conditions in §3 are satisfied.

---

## 3. Success Predicate

**English definition:**

The mission succeeds if and only if, within the time limit T_max:

1. The swarm centroid C(t) crosses the exit boundary X_obs_exit and reaches the goal waypoint g.
2. All 20 modules are located on the far side of the obstacle (X_i > X_obs_exit for all i).
3. The inter-module connectivity graph has remained connected at every 20 Hz tick from t = 0 to t = T_final (no module was ever isolated).
4. No safety violation has been triggered at any tick (E-stop not fired, no module reported a fault that was not cleared within one control cycle).

**Pseudocode:**

```python
def check_obstacle_crossing_success(
    module_positions,       # list of (x, y, z) per module, shape (N, T, 3)
    connectivity_graph,     # list of edge sets per tick, shape (T,)
    centroid_trajectory,    # (T, 3)
    safety_log,             # list of safety events; empty == no violations
    T_max,                  # float, seconds
    tick_dt,                # 0.05 s (20 Hz)
    X_obs_exit,             # float, metres
    goal,                   # (x_g, y_g, tol)
    N=20
) -> bool:

    T = len(centroid_trajectory)
    t_final = T * tick_dt

    # Condition 1: time limit
    if t_final > T_max:
        return False

    # Condition 2: centroid reaches goal
    x_g, y_g, tol = goal
    centroid_final = centroid_trajectory[-1]
    if not (centroid_final[0] > X_obs_exit):
        return False
    if euclidean_2d(centroid_final, (x_g, y_g)) > tol:
        return False

    # Condition 3: all modules on far side at final tick
    final_positions = module_positions[:, -1, :]
    if not all(pos[0] > X_obs_exit for pos in final_positions):
        return False

    # Condition 4: connectivity maintained at every tick
    for t_idx in range(T):
        G = connectivity_graph[t_idx]
        if not is_connected(G, N):
            return False

    # Condition 5: no safety violations
    if len(safety_log) > 0:
        return False

    return True
```

See `predicates.py: check_obstacle_crossing_success()`.

---

## 4. Time Limit

**T_max = 120 s**

**Justification:**

| Component | Budget |
|-----------|--------|
| Pre-crossing reconfiguration (bridge/climb gait setup) | ≤ 20 s |
| Active crossing at ≤ 0.3 m/s over 0.30 m obstacle depth | ≤ 10 s at max speed; budget 30 s for reconfiguration mid-crossing |
| Far-side reformation and centroid-to-goal travel (0.20 m) | ≤ 10 s |
| Connectivity recovery margin (one allowable stall-and-retry) | ≤ 60 s |
| **Total** | **120 s** |

The 120 s limit is conservative enough to allow one full reconfiguration stall-and-retry cycle while remaining well within the 30-minute strut endurance floor. It is tight enough to distinguish successful coordinated crossing from degenerate behaviors such as partial crossing with modules stranded on the obstacle.

---

## 5. Environment Assumptions

**Per P0.3 (baseline environment):**

- Indoor, hard flat surface; no slope on near-side or far-side surfaces.
- Ambient temperature: 10–35 °C.
- Ingress protection: IP40 (no liquid exposure; minor dust tolerated).
- Lighting: sufficient for onboard vision if used; no strong direct sunlight.
- No moving obstacles or humans in the working volume during the trial.

**Obstacle-specific:**

- Obstacle is rigid, non-compliant, and fixed to the ground (zero slip under swarm load).
- Top surface of the obstacle is flat and horizontal (no taper, no rounding) unless explicitly varied in a sub-variant trial.
- Lateral walls of the obstacle are vertical.
- No gap between the ground surface and the obstacle base (flush contact; no underside clearance for modules to pass beneath).
- Trial-to-trial obstacle height is varied uniformly across 40–80 mm; the exact value is provided to the planner before the trial begins (not a hidden parameter).
- No secondary obstacles in the near-side or far-side zones within 0.5 m of the obstacle boundary.

---

## 6. Failure Modes

The following conditions each constitute an explicit mission failure:

| ID | Failure Condition |
|----|-------------------|
| F1 | **Isolation** — any module's connectivity degree drops to zero for ≥ 1 tick and is not restored within 5 ticks (100 ms); the module is considered detached. |
| F2 | **Timeout** — swarm centroid has not crossed X_obs_exit within T_max = 120 s. |
| F3 | **Stranded module** — any module remains at X ≤ X_obs_exit at t = T_max, even if the centroid has crossed. |
| F4 | **E-stop** — any module triggers a hardware E-stop (latency ≤ 50 ms per spec); trial is immediately halted and logged as a safety failure. |
| F5 | **Structural collapse** — the connectivity graph partitions into two or more components for > 5 consecutive ticks, indicating a structural split rather than a transient disconnect. |
| F6 | **Goal miss** — centroid crosses X_obs_exit but does not reach the goal cylinder (radius 0.10 m around g) within T_max. |
| F7 | **Rollback** — swarm centroid regresses to X < X_obs_enter − 0.10 m after having previously advanced past X_obs_enter (pathological retreat). |

F1 and F5 are distinct: F1 is single-module isolation; F5 is a full structural split. Both are failures; F5 is considered more severe and is flagged separately in the trial record.

---

## 7. Scenario Role

**Curriculum placement:** This scenario feeds §2.6 (reconfiguration planning) and §3.4 (connected-gait locomotion), specifically curriculum stages **C4–C6**:

| Stage | Description | Dependency on P0.1(b) |
|-------|-------------|----------------------|
| C4 | Single-gait connected locomotion on flat ground | Baseline; P0.1(a) |
| C5 | Connected-gait climbing over low obstacles (h ≤ 50 mm) | P0.1(b), low-height sub-trials |
| C6 | Adaptive reconfiguration mid-crossing (h = 50–80 mm) | P0.1(b), high-height sub-trials; requires planner graduation from C5 |

P0.1(b) is specifically designed to stress the boundary between single-module capability (≤ 30 mm) and collective-only capability (40–80 mm), making it the canonical scenario to validate that the planner correctly identifies when individual climbing fails and collective bridging is required. Planner policies trained on C4 alone will fail P0.1(b); success requires explicit connectivity-preserving reconfiguration strategies learned through C5–C6 exposure.

The scenario also provides the primary data source for measuring reconfiguration overhead (time spent in non-locomotion reconfiguration poses) as a function of obstacle height, which is a key metric for §3.4 curriculum pacing decisions.

---

## 8. Notes / Open Items

- **Bridge vs. climb gait selection:** The planner must choose between a caterpillar-bridge gait (modules form a ramp over the obstacle) and a collective-climb gait (swarm flows up and over as a deformable body). Both are valid; the scenario does not mandate one. Performance comparison across gait families is an open research question for C5–C6.

- **Obstacle height as a trial parameter:** The 40–80 mm range is chosen to span the single-module/collective threshold. Sub-trial sets at fixed heights (40, 50, 60, 70, 80 mm) should be run separately for curriculum calibration before mixed-height trials.

- **Connectivity graph computation:** At 20 Hz with 20 modules, the connectivity check runs every 50 ms. The exact physical-layer definition of a "connected edge" (docking latch engaged vs. proximity threshold vs. communication link active) must be finalized before P0.1(b) trials begin. Current working assumption: latch-engaged signal from the docking mechanism is the authoritative edge source.

- **Partial success metric:** Binary success/failure (§3) is the primary metric, but partial-crossing distance at T_max is recorded as a secondary metric to track curriculum progress when the swarm fails to complete the crossing.

- **Obstacle variants (future):** Ramped obstacles, multiple steps, and irregular block arrangements are deferred to P0.2 (unstructured terrain). P0.1(b) uses only uniform rectangular steps.

- **Communication during crossing:** When modules are stacked vertically on the obstacle, IR line-of-sight (Layer 1) may be occluded. ESP-NOW mesh (Layer 2) must maintain the control loop. This should be explicitly verified in early P0.1(b) hardware trials before curriculum progression to C5.

- **`predicates.py` status:** `check_obstacle_crossing_success()` is stubbed; connectivity graph input format (`is_connected` function signature and edge representation) must be confirmed against the swarm runtime's telemetry schema before integration testing.
