# Mission D — Object Manipulation (P0.1(d))

## 1. Mission Overview

Mission D tasks the swarm with achieving a specified 6-DOF pose of a target object within a constrained workspace. Unlike transport missions (P0.1(c)), which define success as delivering an object to a goal zone, success here is defined by the object reaching a precise target pose: position within ±30 mm on all axes and orientation within ±10° on all axes, held stably. The swarm reconfigures around the object—encircling it, establishing contact points, and applying coordinated forces and moments—to tilt, rotate, slide, or edge-lift the object into the goal configuration. No displacement beyond the local workspace is intended; the object begins and ends within a 1 m × 1 m region. This is the highest-DOF manipulation task in the curriculum and serves as the terminal challenge for swarm dexterity evaluation.

---

## 2. Initial Conditions

### Object
| Parameter | Value |
|---|---|
| Shape | Rigid rectangular panel |
| Dimensions | 300 mm × 200 mm × 20 mm |
| Mass | ≤ 500 g |
| Initial pose | Flat on floor, centroid at workspace origin (0, 0, 0), long axis aligned with +X |
| Surface | Smooth-to-moderate friction (μ ∈ [0.3, 0.6] on hard flat floor) |

### Swarm
| Parameter | Value |
|---|---|
| Modules | 12 struts + 8 nodes (20 total) |
| Strut length | 220 mm |
| Node diameter | 90 mm |
| Starting formation | Ring within 400 mm of object centroid, distributed approximately uniformly in azimuth |
| Tick rate | 20 Hz |
| Max collective speed | 0.3 m/s |

### Goal Vector
The goal vector **g** encodes the target 6-DOF pose of the object:

```
g = (x_t, y_t, z_t, roll_t, pitch_t, yaw_t)
```

- **Position target** (x_t, y_t, z_t): offset from initial centroid, within workspace bounds
- **Orientation target** (roll_t, pitch_t, yaw_t): Euler angles relative to initial orientation
- Tolerances: position ±30 mm per axis, orientation ±10° per axis
- **g** is injected at mission start; swarm must plan and execute without re-injection

---

## 3. Success Predicate

### English

The mission is successful when all of the following hold simultaneously:

1. The object centroid is within ±30 mm of the target position on each axis.
2. The object orientation is within ±10° of the target orientation on each of roll, pitch, and yaw.
3. The object is stationary: estimated object velocity < 0.02 m/s for a continuous window of ≥ 1 second.
4. No safety violation has occurred at any point during the mission (no e-stop trigger, no collision event above threshold, no module fault).
5. The predicate is satisfied before the mission time limit expires.

### Pseudocode

```python
def check_manipulation_success(state, goal, history, t_now, t_limit):
    obj = state.object

    # 1. Position check
    pos_err = abs(obj.centroid - goal.position)  # per-axis, meters
    if any(pos_err > 0.030):
        return False, "position_error"

    # 2. Orientation check
    ori_err = angle_diff_euler(obj.orientation, goal.orientation)  # per-axis, degrees
    if any(ori_err > 10.0):
        return False, "orientation_error"

    # 3. Stationarity check — requires 1 s window at 20 Hz = 20 consecutive ticks
    recent = history[-20:]  # last 1 s of ticks
    if len(recent) < 20:
        return False, "insufficient_history"
    if any(tick.object_velocity >= 0.02 for tick in recent):
        return False, "not_stationary"

    # 4. Safety check
    if state.safety_violation:
        return False, "safety_violation"

    # 5. Time check
    if t_now > t_limit:
        return False, "timeout"

    return True, "success"
```

See `predicates.py`: `check_manipulation_success()`

---

## 4. Time Limit

**Time limit: 120 seconds**

**Justification:**

The manipulation task requires the swarm to (a) sense the current object pose, (b) plan a multi-contact manipulation strategy, (c) reconfigure to establish contact, and (d) execute coordinated force application through potentially multiple intermediate configurations. Each sub-phase is estimated conservatively:

| Sub-phase | Estimated duration |
|---|---|
| Pose sensing + goal parsing | ≤ 2 s |
| Manipulation planning | ≤ 5 s |
| Reconfiguration to contact positions | ≤ 20 s |
| Active manipulation (may require multiple contact cycles) | ≤ 60 s |
| Settling + stationarity verification (≥ 1 s required) | ≤ 5 s |
| Margin | 28 s |
| **Total** | **120 s** |

The 120 s limit is consistent with the instruction-to-activation bound (≤ 10 s, P0.4) being a subset of mission setup time, and with endurance constraints (struts ≥ 30 min, nodes ≥ 60 min). A 2-minute active manipulation window is well within strut endurance and represents the most complex motion primitive in the curriculum; exceeding 120 s indicates a failed strategy, not insufficient time.

---

## 5. Environment Assumptions

### Per P0.3 Constraints
- **Surface:** Indoor, hard flat floor (concrete, tile, or equivalent)
- **Temperature:** 10–35 °C operating range
- **Ingress protection:** IP40 (no liquid exposure, limited particulate)
- **Lighting:** Sufficient for onboard sensing; no direct sunlight glare requirement enforced for this mission

### Object Surface Friction
- Coefficient of static friction μ_s ∈ [0.3, 0.6] between object and floor
- Coefficient of static friction between module contact surfaces and object: μ_s ∈ [0.4, 0.7] (rubber-tipped actuator contact assumed)
- Object is treated as rigid; no deformation modeled

### Workspace Boundary
- **Footprint:** 1 m × 1 m, centered on object initial centroid
- **Height:** Object z-axis displacement ≤ 150 mm (edge-lift scenarios only; no full airborne lift)
- All modules must remain within a 1.5 m × 1.5 m safety perimeter throughout the mission
- Object must not cross workspace boundary at any point; crossing constitutes a failure mode (see §6)

---

## 6. Failure Modes

| ID | Failure Mode | Detection | Recovery Hint |
|---|---|---|---|
| F-D1 | **Object exits workspace** | Object centroid or any corner crosses 1 m × 1 m boundary | Abort manipulation; replan from boundary-aware contact positions |
| F-D2 | **Object uncontrolled / dropped** | Object velocity > 0.3 m/s or object enters free-fall (z acceleration > 5 m/s²) | Immediate e-stop (≤ 50 ms); declare failure |
| F-D3 | **Pose not achieved at time limit** | `t_now > t_limit` and success predicate not satisfied | Log final pose error; classify as timeout failure |
| F-D4 | **Safety violation** | E-stop triggered, module fault, inter-module collision above force threshold | Halt all motion; log fault state; declare failure |
| F-D5 | **Contact loss during manipulation** | Estimated contact force drops to zero while object not yet at goal | Replan contact configuration; retry up to 2 times before declaring failure |
| F-D6 | **Goal infeasible** | Planner cannot find valid manipulation sequence given current contact geometry | Declare planning failure at t < 15 s; do not consume full time limit |

---

## 7. Scenario Role

Mission D occupies the terminal position in the swarm manipulation curriculum. Within the broader master plan architecture:

- **§2.6 (Manipulation Primitives):** Mission D is the integration test for all manipulation primitives developed in §2.6, including edge-contact force application, coordinated moment generation, and multi-point grasp reconfiguration. It validates that primitives compose correctly under a unified planner.
- **§3.4 (Curriculum Sequencing):** Mission D corresponds to curriculum stages **C5–C6**. C5 introduces pose-constrained manipulation with a single target DOF (e.g., yaw-only rotation); C6 requires full 6-DOF pose achievement including edge-lift. Agents must have passed Missions A–C before attempting Mission D. Failure rate targets for curriculum gating: C5 pass rate ≥ 80% before C6 exposure; C6 pass rate ≥ 70% before Mission D is scored as complete.

Mission D is intentionally the hardest manipulation task: it combines the highest DOF target, the tightest pose tolerances, and the largest planning burden of any scenario in the suite. A swarm that reliably passes Mission D under randomized **g** vectors demonstrates sufficient dexterity for field deployment in structured manipulation contexts.

---

## 8. Notes / Open Items

- **Pose estimation source:** The current specification assumes an external ground-truth pose sensor (motion capture or overhead camera) for object state during development and evaluation. Onboard-only pose estimation using strut/node contact feedback is an open research item; accuracy against the ±30 mm / ±10° tolerance is unvalidated.
- **Friction uncertainty:** The μ ∈ [0.3, 0.6] range spans a factor of 2 in friction force. The planner must either estimate μ online or plan conservatively for the lower bound. No online friction estimation module is currently specified.
- **Edge-lift height limit (150 mm):** This is a provisional safety cap. Structural loading on strut modules during edge-lift has not been fully characterized; the 150 mm limit may need revision based on hardware testing.
- **Goal vector injection mechanism:** **g** format and injection API are not yet standardized across orchestrator and swarm interface. A schema definition for `goal_vector_d` should be added to `interfaces/mission_goals.py` before integration testing.
- **Stationarity window at 20 Hz:** The 20-tick (1 s) stationarity requirement at 20 Hz is sensitive to sensor noise in the object velocity estimate. A low-pass filter cutoff for velocity estimation should be specified in `predicates.py` alongside `check_manipulation_success()`.
- **Multi-contact replan limit:** The F-D5 retry limit of 2 replans is a placeholder. Empirical data from C5/C6 trials should inform the final limit.
- **Interaction with transport missions:** The workspace boundary (1 m × 1 m) is smaller than transport mission goal zones. Ensure that orchestrator does not inject a transport-class **g** vector into a Mission D context; type-checking on the goal schema is recommended.
