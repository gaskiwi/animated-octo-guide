# Mission P0.1(c) — Cooperative Transport of a Payload

---

## 1. Mission Overview

Twenty FreeSN modules (12 struts, 8 nodes) cooperatively transport a rigid payload from a designated start zone to a marked drop zone at least 1.0 m away on a flat indoor surface. No fewer than four struts make sustained contact with the payload throughout the transit, distributing the ≤700 g load across the formation. The orchestrator issues a single high-level goal vector encoding the drop-zone centroid; the swarm autonomously forms a carrying configuration, translates to the target, and releases the payload within the drop zone. The mission validates distributed load sharing, formation-speed control under load, and graceful handoff at delivery — the three competencies required before advancing to curriculum stages C5–C6.

---

## 2. Initial Conditions

### 2.1 Payload

| Property | Value |
|---|---|
| Shape | Rigid rectangular box |
| Dimensions | 150 mm × 150 mm × 100 mm (L × W × H) |
| Mass | ≤ 700 g (= 2 × single module mass cap of 350 g) |
| Surface | Smooth ABS, kinetic friction µ_k ≈ 0.35 on hard floor (see §5) |
| Centroid (world frame) | (0.000, 0.000, 0.050) m |
| Orientation | Upright; top face parallel to floor (±2°) |

### 2.2 Drop Zone

| Property | Value |
|---|---|
| Shape | Square, 300 mm × 300 mm |
| Center (world frame) | (1.200, 0.000, 0.000) m |
| Marking | High-contrast floor tape, visible to node cameras |
| Distance from payload start | 1.200 m (≥ 1.0 m minimum per §2.6) |

### 2.3 Goal Vector

```
g = {
    "target_centroid": [1.200, 0.000, 0.050],   # m, world frame
    "drop_zone_half_extent": 0.150,              # m (300 mm zone → ±150 mm)
    "success_radius": 0.050,                     # m (±50 mm tighter check)
    "release_on_arrival": true
}
```

### 2.4 Module Starting Positions

All positions are centroid locations in the world frame (m). Heading θ is the long-axis azimuth for struts (degrees, CCW from +X), irrelevant for nodes.

#### Load-Bearing Struts (4) — engaging payload at mission start

| ID | X (m) | Y (m) | Z (m) | θ (°) | Contact face |
|---|---|---|---|---|---|
| S01 | +0.185 | 0.000 | 0.050 | 180 | Payload +X face |
| S02 | −0.185 | 0.000 | 0.050 | 0 | Payload −X face |
| S03 | 0.000 | +0.185 | 0.050 | 270 | Payload +Y face |
| S04 | 0.000 | −0.185 | 0.050 | 90 | Payload −Y face |

Each load-bearing strut tip is flush against the corresponding 150 mm face; the opposite tip extends outward 220 mm to provide a moment arm for lateral force application.

#### Support Struts (8) — positioned in outer ring, not yet attached

| ID | X (m) | Y (m) | Z (m) | θ (°) | Role |
|---|---|---|---|---|---|
| S05 | +0.380 | +0.200 | 0.050 | 160 | +X/+Y diagonal brace (standby) |
| S06 | +0.380 | −0.200 | 0.050 | 200 | +X/−Y diagonal brace (standby) |
| S07 | −0.380 | +0.200 | 0.050 | 340 | −X/+Y diagonal brace (standby) |
| S08 | −0.380 | −0.200 | 0.050 | 20 | −X/−Y diagonal brace (standby) |
| S09 | 0.000 | +0.380 | 0.050 | 270 | +Y rear guard |
| S10 | 0.000 | −0.380 | 0.050 | 90 | −Y rear guard |
| S11 | +0.300 | 0.000 | 0.050 | 180 | +X leader |
| S12 | −0.300 | 0.000 | 0.050 | 0 | −X tail |

#### Nodes (8) — distributed around formation perimeter

| ID | X (m) | Y (m) | Z (m) | Role |
|---|---|---|---|---|
| N01 | +0.280 | +0.280 | 0.045 | Corner relay, +X/+Y |
| N02 | +0.280 | −0.280 | 0.045 | Corner relay, +X/−Y |
| N03 | −0.280 | +0.280 | 0.045 | Corner relay, −X/+Y |
| N04 | −0.280 | −0.280 | 0.045 | Corner relay, −X/−Y |
| N05 | +0.450 | 0.000 | 0.045 | Forward scout / drop-zone detector |
| N06 | −0.450 | 0.000 | 0.045 | Rear anchor |
| N07 | 0.000 | +0.450 | 0.045 | Lateral range sensor |
| N08 | 0.000 | −0.450 | 0.045 | Lateral range sensor |

> **Note:** Z = 0.050 m (strut centroids) reflects struts lying horizontally at axle height. Z = 0.045 m (node centroids) reflects nodes resting on the floor with Ø90 mm body. Adjust if struts are oriented with long axis vertical in the reference implementation.

---

## 3. Success Predicate

### 3.1 English

The mission succeeds when all of the following hold simultaneously:

1. The payload centroid lies within the drop zone (horizontal distance from drop-zone center ≤ 50 mm).
2. The payload has been stationary (all linear velocity components < 0.02 m/s) for at least 1.0 s continuously.
3. At least 2 struts remain in physical contact with the payload at the moment delivery is declared.
4. No safety violation has been triggered at any point during the mission (E-stop never latched, no module collision above threshold, no out-of-bounds exit).
5. All of the above are satisfied before the time limit expires.

### 3.2 Pseudocode

```python
def check_transport_success(state, history, config) -> bool:
    t_now = state.sim_time

    # 1. Payload centroid in drop zone
    payload_xy = state.payload.centroid[:2]
    dz_center  = config.drop_zone_center[:2]
    if norm(payload_xy - dz_center) > config.success_radius:   # 0.050 m
        return False

    # 2. Payload stationary for >= 1.0 s
    stationary_duration = 0.0
    for snap in reversed(history):                  # newest first, 20 Hz
        if norm(snap.payload.velocity) < 0.02:      # m/s
            stationary_duration += 1.0 / config.tick_rate
        else:
            break
    if stationary_duration < 1.0:
        return False

    # 3. At least 2 struts attached at delivery
    attached = sum(
        1 for s in state.struts
        if s.contact_with_payload and s.contact_duration > 0.0
    )
    if attached < 2:
        return False

    # 4. No safety violation in mission history
    if any(snap.safety_violation for snap in history):
        return False

    # 5. Within time limit
    if t_now > config.time_limit:
        return False

    return True
```

### 3.3 Implementation Reference

```
See predicates.py: check_transport_success()
```

---

## 4. Time Limit

**T_limit = 120 s**

| Component | Estimate |
|---|---|
| Swarm activation (P0.4 budget) | ≤ 10 s |
| Formation closure around payload | ≤ 15 s |
| Transit at nominal speed (0.15 m/s over 1.2 m) | ≈ 8 s |
| Deceleration and precise placement at drop zone | ≤ 10 s |
| Margin for coordination overhead, replanning, obstacle avoidance | × 3.5 safety factor |
| **Total** | **≤ 120 s** |

A 120 s cap places a meaningful constraint on formation-search and replanning loops without punishing nominal transport, which completes in ~43 s under typical coordination overhead. The 3.5× margin accommodates the worst-case initial configuration (modules spread at max standby radius) and one replan cycle. Tightening to 90 s is feasible once formation convergence is benchmarked.

---

## 5. Environment Assumptions

All conditions are per operating envelope P0.3 unless noted.

| Parameter | Value / Constraint |
|---|---|
| Surface | Hard, flat floor (concrete, tile, or equivalent); slope ≤ 0.5° |
| Ambient temperature | 10–35 °C |
| Humidity | Non-condensing |
| Ingress protection | IP40 (indoor only, no liquid exposure) |
| Lighting | ≥ 200 lux; no direct sunlight on floor markers |
| Payload surface friction | Kinetic µ_k = 0.30–0.40 (smooth ABS on hard floor); static µ_s ≤ 0.50. Swarm force budget must not assume µ_k > 0.35 |
| Payload tip stability | Box aspect ratio 1.5:1.5:1 ensures CG well within base when upright; tipping threshold is ~34° lateral tilt |
| Floor cleanliness | No loose debris >5 mm in the 2 m × 1 m operating corridor |
| External interference | None (no wind, no human foot traffic during trial) |
| IR/ultrasound interference | Nil (single trial at a time) |

---

## 6. Failure Modes

| ID | Condition | Detection | Recovery Allowed? |
|---|---|---|---|
| F-C1 | **Payload dropped** — no strut reports physical contact with payload for > 2.0 s continuously | Contact sensors on all struts, verified each tick | No; mission terminates immediately with FAIL |
| F-C2 | **Payload outside drop zone at time limit** — payload centroid > 50 mm from drop-zone center when t ≥ T_limit | Evaluated at tick when t = T_limit | No; time limit is hard |
| F-C3 | **Safety violation** — E-stop latched, module-to-module collision force > threshold, or any module exits the 3 m × 2 m operating area | Safety monitor (≤ 50 ms latency per P0.4) | No; E-stop halts all actuators |
| F-C4 | **Payload tipped over** — payload orientation error (angle between payload top-face normal and world +Z) > 45° for > 0.5 s | IMU on payload or vision-based pose estimate | No; payload integrity compromised |

> **F-C1 grace window:** The 2.0 s no-contact window allows brief strut repositioning maneuvers without penalising intentional mid-transit grip transfers. Any window > 2.0 s is scored as a drop regardless of intent.

---

## 7. Scenario Role

Mission P0.1(c) occupies a specific slot in the §2.6 scenario suite and §3.4 training curriculum:

- **§2.6 scenario suite:** P0.1(c) is the third entry in the P0.1 object-interaction block (after P0.1(a) approach/surround and P0.1(b) push-to-zone). It is the first scenario requiring sustained multi-module load sharing rather than single-point contact, and it introduces the `goal_vector` drop-zone encoding used by all subsequent transport scenarios.

- **§3.4 curriculum C5 — Distributed load sharing:** The four-strut minimum engagement rule and the contact-duration tracking in `check_transport_success()` directly exercise the C5 competency: modules must negotiate role assignments (load-bearer vs. scout vs. lateral brace) and maintain them across a full transit.

- **§3.4 curriculum C6 — Cooperative manipulation under load:** The deceleration and precision-placement phase at the drop zone exercises C6: the formation must slow from transit speed, tighten its grasp geometry to reduce payload swing, and achieve sub-50 mm placement accuracy while still satisfying the ≥2-strut attachment constraint at handoff.

Passing P0.1(c) is a prerequisite gate for the C6 capstone (P0.2: transport over a 0.5 m ramp) defined in §3.4.

---

## 8. Notes / Open Items

| # | Item | Owner | Status |
|---|---|---|---|
| N-C1 | **Payload IMU vs. vision pose:** Orientation failure mode F-C4 requires payload pose. It is unresolved whether the payload carries a small IMU tag or pose is estimated from strut kinematics + node cameras. IMU tag is cleaner but adds ≈30 g to payload. | Hardware lead | Open |
| N-C2 | **Grip force model:** Strut contact is currently modelled as point contact with Coulomb friction. If strut tips are replaced with compliant pads (µ_k up to 0.55), the 4-strut minimum could potentially be relaxed to 3. Requires physical characterisation. | Mechanical | Open |
| N-C3 | **Drop-zone detection latency:** N05 (forward scout node) must detect the floor-tape marker before the formation enters the deceleration zone (~300 mm from target). At 0.15 m/s nominal this gives ≈2 s detection window. Camera frame rate and lighting floor must be verified. | Firmware | Open |
| N-C4 | **F-C1 grace window value:** 2.0 s is provisional. If formation replanning requires longer grip transfers (e.g., doorway squeeze scenarios in C6+), this may need extending to 3.0 s with a corresponding reduction in transport speed. | Curriculum | Open |
| N-C5 | **`predicates.py` stub:** `check_transport_success()` is stubbed; full integration with the physics sim contact-sensor API is pending. See issue tracker. | Sim team | Open |
| N-C6 | **Multi-trial repeatability:** Starting positions in §2.4 represent the nominal configuration. A jitter of ±20 mm per module and ±5° heading should be applied across the §2.6 evaluation suite to test robustness of formation-closure algorithms. | Test | Pending |
