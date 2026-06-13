# Interface Control Document — FreeSN Prototype Swarm
**Version:** 0.9 (Phase 1 draft)  
**Status:** Draft — pending Phase 4 calibration measurements  
**Date:** 2026-06  
**Governed by:** Master Plan §2.2–2.4, CN-002 (two-layer comms architecture)  
**Scope:** Yoo Modular Robotic Swarm, Tier P0.2 Prototype — ≤20 modules (12 struts + 8 nodes)

---

## Document Control

This document is the single normative source for all hardware and software interfaces across the FreeSN modular swarm. It covers:

- Communications protocol byte layouts (Layers 1 and 2)
- Timing and synchronization requirements
- Electrical block diagrams, pin assignments, and connector interfaces
- Safety-critical signal paths

**Authority:** Master Plan v2.0 §2.2–2.4 and CN-002. Frozen parameters (Appendix A) may not be changed without a formal plan revision; all other fields require a change note referencing the affected section and the responsible phase (P_x.y).

**Change procedure:** Propose change in a pull request against this file. Change note must state: (1) section(s) affected, (2) reason, (3) responsible phase, (4) impact on frozen-parameter table. Merge requires sign-off from the plan authority.

**Relationship to other documents:**
- Master Plan §0.0 — frozen parameter definitions (reproduced in Appendix A)
- DR (Design Review) notes — linked per section where measurements are pending
- `guardrails.md` — escalation thresholds and override rules (not reproduced here)

---

## 1. System Overview

The swarm employs a hierarchical, real-time communication fabric split by function and latency requirement.

### 1.1 Two-Layer Architecture

**Layer 1 — IR/UART-over-IR (link-local, deterministic):**  
Per-tick, point-to-point exchange between struts and nodes at each docking connector. Every 50 ms, each strut transmits a 30-byte actuation-query message to its connected node; the node responds with a 28-byte broadcast carrying policy-derived motor commands to all struts in its subtree. Collision avoidance is achieved via TDMA slot assignment by module ID. Effective payload bandwidth: ~1.2 kbps per link; ~24 kbps aggregate for a fully connected 20-module tree (see §4).

**Layer 2 — ESP-NOW 2.4 GHz (swarm-wide, asynchronous):**  
Goal vector diffusion (128-d float16, ~300 bytes) on version change or every 2 s maximum; safety broadcasts (ARM, E-STOP, GEOFENCE) delivered with high-priority FreeRTOS queuing; sparse telemetry uplink. Sustained bandwidth: <10 kbps; peak during goal gossip: <50 kbps.

### 1.2 Module Topology

| Role | Count (P0.2) | Module ID Range | Primary Function |
|------|-------------|-----------------|------------------|
| Strut | 12 | 0–11 | Linear member; carries IMU, gimbal motors, battery; runs local observation; reports per-tick to connected node |
| Node | 8 | 12–19 | Structural hub; aggregates strut observations; executes CTDE/MAPPO inference; broadcasts action commands; maintains ESP-NOW presence |

### 1.3 Authentication and Integrity

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| Layer 1 | CRC-16 CCITT (poly 0x1021, init 0xFFFF) | Header + payload integrity |
| Layer 2 | HMAC-SHA256 truncated to 32 bits | Per-packet authentication; pre-shared per-swarm key |
| Flash | AES-128 at rest | Goal vector and key material |

---

## 2. Message Schemas

### 2.1 Layer 1 (IR) — Per-Tick Messages

#### 2.1.1 Strut → Node Message (Per-Tick Query)

**Total size:** 30 bytes | **Frequency:** 20 Hz (every 50 ms) | **Direction:** Strut → Node (unicast on dock IR)

| Byte(s) | Field | Type | Size | Description |
|---------|-------|------|------|-------------|
| 0 | `msg_type` | u8 | 1 | Message class. 0x01 = STRUT_TO_NODE (see §2.3). |
| 1–2 | `strut_id` | u16 LE | 2 | Originating strut module ID (0–19; typically 0–11 in P0.2). |
| 3 | `connector_id` | u8 | 1 | Docking port on strut (0–25; typically 0–7 in P0.2). Identifies which face of the strut is transmitting. |
| 4–5 | `tick` | u16 LE | 2 | Monotonic tick counter (0–65535, wraps). Receiver uses to detect missed ticks and message age. |
| 6 | `goal_version` | u8 | 1 | Current goal vector version (0–255) known to this strut. Node caches version to detect mid-episode goal updates. |
| 7 | `seq` | u8 | 1 | Sequence number within tick (0–255). Unused in P0.2 (single query per strut per tick); reserved for future multi-fragment support. |
| 8–9 | `reserved` | u8[2] | 2 | Reserved; set to 0x00 by sender, ignored by receiver. |
| 10–11 | `crc16` | u16 LE | 2 | CRC-16 CCITT of bytes 0–9 (header only). **[OPEN-001 — measure placement in P4.7]** |
| 12–27 | `payload` | i8[16] | 16 | Policy observation: 16-element int8 encoding of strut-local state (joint angles, angular velocities, contact flags, battery SoC). Quantized from f32 per §2.1.3. Range: [−128, +127]. |

**Validation rules at receiver (node):**
- Accept only if `strut_id` matches expected peer for this IR RX port.
- Accept only if `tick` age ≤ 2 ticks (100 ms); discard and flag stale otherwise.
- CRC-16 must match; discard silently on failure and increment `rx_crc_err` counter.
- Node tracks `goal_version` from each strut; if any strut lags by >2 versions, node requests goal re-diffusion via Layer 2.

#### 2.1.2 Observation Payload Quantization (Strut → Node)

Quantization from float32 observation `x` to int8 encoding `q`:

```
q = clamp(round(x * 127 / obs_max[i]), -128, 127)
```

Dequantization on node receipt:

```
x_hat = q * obs_max[i] / 127
```

`obs_max[i]` is per-dimension and frozen (see Appendix A). Error from quantization is bounded by `obs_max[i] / 127`.

#### 2.1.3 Node → Struts Broadcast (Per-Tick Response)

**Total size:** 28 bytes | **Frequency:** 20 Hz (every 50 ms) | **Direction:** Node → All Connected Struts (broadcast on dock IR)

| Byte(s) | Field | Type | Size | Description |
|---------|-------|------|------|-------------|
| 0 | `msg_type` | u8 | 1 | Message class. 0x02 = NODE_BCAST (see §2.3). |
| 1–2 | `node_id` | u16 LE | 2 | Originating node module ID (typically 12–19 in P0.2). |
| 3–4 | `tick` | u16 LE | 2 | Monotonic tick counter matching Layer 1 master clock epoch. |
| 5 | `goal_version` | u8 | 1 | Goal vector version currently cached by this node. Struts compare against their own `goal_version`; mismatch triggers Layer 2 resync request. |
| 6 | `quorum_active` | u8 | 1 | Boolean flag (0x00 or 0x01). Set to 0x01 iff ≥80% of connected struts have reported this tick. If 0x00 persists >2 s, all struts must freeze (see §5). |
| 7–8 | `crc16` | u16 LE | 2 | CRC-16 CCITT of bytes 0–6 (header). **[OPEN-001]** |
| 9–10 | `hmac16` | u16 LE | 2 | HMAC-SHA256 truncated to 16 bits; covers bytes 0–10. **[OPEN-002 — derive truncation in P4.7]** |
| 11 | `reserved` | u8 | 1 | Reserved; set to 0x00. |
| 12–27 | `payload` | i8[16] | 16 | Policy action: 16-element int8 motor command vector. Node's CTDE/MAPPO decoder produces this from aggregated observations. Quantized [−128, +127]; same format as observation payload. Broadcast identically to all connected struts in this tick. |

**Notes:**
- Node transmits after the TDMA RX collection window (see §3.1).
- Each strut applies the action payload to its motor servos within the same tick.
- `quorum_active = 0` for >2 s is a system-level safety trigger: all struts must stop and hold position.
- Action payload is not per-strut-customized in P0.2; all struts in a node's subtree receive identical commands.

---

### 2.2 Layer 2 (ESP-NOW) — Goal, Safety, Telemetry

#### 2.2.1 Goal Diffusion Packet

**Total size:** 300 bytes | **Frequency:** On goal version increment OR every 2 s maximum | **Direction:** Broadcast (all nodes and struts listen)

| Byte(s) | Field | Type | Size | Description |
|---------|-------|------|------|-------------|
| 0 | `msg_type` | u8 | 1 | Message class. 0x10 = GOAL_DIFFUSION (see §2.3). |
| 1 | `goal_version` | u8 | 1 | New goal vector version (0–255, wraps). Receivers cache this value; duplicate `goal_version` packets are accepted (idempotent update) but only re-diffuse if >2 s since last diffusion. |
| 2–3 | `source_id` | u16 LE | 2 | Originating module ID (node IDs 12–19, or 0xFFFF = orchestrator). |
| 4–5 | `seq` | u16 LE | 2 | Packet sequence number (for future multi-packet reassembly; always 0 in P0.2). |
| 6 | `total_packets` | u8 | 1 | Total packets in this diffusion burst (always 1 in P0.2; future: >1 for larger goal vectors). |
| 7 | `packet_index` | u8 | 1 | This packet's zero-based index within the burst (always 0 in P0.2). |
| 8–11 | `hmac32` | u32 LE | 4 | HMAC-SHA256 truncated to 32 bits covering bytes 0–7 and the goal payload. Pre-shared per-swarm key. **[OPEN-002]** |
| 12–267 | `goal_vector` | f16[128] | 256 | Goal vector: 128 float16 (IEEE 754 half-precision) values encoding the high-level task objective. Byte order: little-endian per element. |
| 268–299 | `reserved` | u8[32] | 32 | Reserved for future metadata (task ID, priority, TTL). Set to 0x00 by sender; ignored by receiver in P0.2. |

**Diffusion rules:**
- Source broadcasts once on the ESP-NOW channel; all peer modules rebroadcast once each (gossip, one hop).
- A module that receives a `goal_version` already cached does not rebroadcast, preventing storms.
- If no goal diffusion is received within 4 s, nodes enter QUORUM_HOLD and freeze struts pending resync.

#### 2.2.2 Safety Broadcast (ARM / E-STOP / GEOFENCE)

**Total size:** 16 bytes | **Frequency:** On demand (event-driven) | **Direction:** Broadcast (high-priority FreeRTOS queue)

| Byte(s) | Field | Type | Size | Description |
|---------|-------|------|------|-------------|
| 0 | `msg_type` | u8 | 1 | 0x11 = ARM, 0x12 = E_STOP, 0x13 = GEOFENCE (see §2.3). |
| 1–2 | `source_id` | u16 LE | 2 | Issuing node or orchestrator ID. |
| 3–4 | `tick` | u16 LE | 2 | Tick value at time of issue. Receivers check tick freshness (age < 200 ms = 4 ticks); stale packets are dropped and logged. |
| 5–8 | `hmac32` | u32 LE | 4 | HMAC-SHA256 truncated to 32 bits; covers bytes 0–4. Authentication is mandatory; unauthenticated safety packets are dropped and logged. **[OPEN-002]** |
| 9 | `param0` | u8 | 1 | Command-specific parameter 0. ARM: 0x00 = disarm, 0x01 = arm. E_STOP: 0x00 = immediate, 0x01 = graceful decel. GEOFENCE: violation zone ID. |
| 10 | `param1` | u8 | 1 | Command-specific parameter 1. Reserved in P0.2; set to 0x00. |
| 11 | `param2` | u8 | 1 | Command-specific parameter 2. Reserved in P0.2; set to 0x00. |
| 12–15 | `reserved` | u8[4] | 4 | Reserved; set to 0x00. |

**Safety packet handling requirements (all modules):**
- E_STOP must be processed within one FreeRTOS tick (≤1 ms) of receipt; motor driver nSLEEP must be de-asserted within 5 ms.
- ARM disarm must transition state machine to IDLE (see §5).
- GEOFENCE triggers a soft E_STOP with graceful deceleration over ≤2 ticks (100 ms).
- All safety events must be logged to flash with tick timestamp for post-mortem.

#### 2.2.3 Telemetry Uplink

**Total size:** 8 + N bytes (variable) | **Frequency:** Sparse / on-demand | **Direction:** Module → Orchestrator (unicast via ESP-NOW)

| Byte(s) | Field | Type | Size | Description |
|---------|-------|------|------|-------------|
| 0 | `msg_type` | u8 | 1 | 0x20 = TELEMETRY (see §2.3). |
| 1–2 | `module_id` | u16 LE | 2 | Reporting module. |
| 3–4 | `tick` | u16 LE | 2 | Tick at time of measurement. |
| 5 | `telem_type` | u8 | 1 | Sub-type: 0x01 = battery, 0x02 = thermal, 0x03 = imu_raw, 0x04 = motor_fault, 0x05 = rx_stats. |
| 6–7 | `length` | u16 LE | 2 | Byte count of `payload` field. |
| 8–(8+N−1) | `payload` | u8[N] | N | Telemetry payload; format is telem_type-specific (see sub-sections below). |

**Telemetry payload formats by sub-type:**

| `telem_type` | N (bytes) | Payload fields |
|--------------|-----------|---------------|
| 0x01 battery | 4 | u16 LE: Vbat_mV; u8: SoC_pct (0–100); u8: alert_flags (bit0=low_volt, bit1=critical) |
| 0x02 thermal | 2 | i8: mcu_temp_C; i8: motor_temp_C (if available) |
| 0x03 imu_raw | 12 | i16 LE × 3: accel_x/y/z (LSB=1/32768 g at ±16g); i16 LE × 3: gyro_x/y/z (LSB=1/16 °/s at ±2000°/s) |
| 0x04 motor_fault | 2 | u8: driver_id (0 or 1); u8: nFAULT_code (0x00=clear, 0x01=overcurrent, 0x02=thermal_shutdown) |
| 0x05 rx_stats | 6 | u16 LE: rx_good; u16 LE: rx_crc_err; u16 LE: rx_timeout (per Layer 1 port, per 1 s window) |

---

### 2.3 Message Type Registry

| Code | Name | Layer | Direction | Nominal Size |
|------|------|-------|-----------|-------------|
| 0x01 | STRUT_TO_NODE | Layer 1 (IR) | Strut → Node | 30 bytes |
| 0x02 | NODE_BCAST | Layer 1 (IR) | Node → Struts | 28 bytes |
| 0x10 | GOAL_DIFFUSION | Layer 2 (ESP-NOW) | Broadcast | 300 bytes |
| 0x11 | ARM | Layer 2 (ESP-NOW) | Broadcast | 16 bytes |
| 0x12 | E_STOP | Layer 2 (ESP-NOW) | Broadcast | 16 bytes |
| 0x13 | GEOFENCE | Layer 2 (ESP-NOW) | Broadcast | 16 bytes |
| 0x20 | TELEMETRY | Layer 2 (ESP-NOW) | Module → Orch. | 8 + N bytes |
| 0x03–0x0F | _reserved_L1_ | Layer 1 | — | — |
| 0x14–0x1F | _reserved_safety_ | Layer 2 | — | — |
| 0x21–0xFF | _reserved_ | — | — | — |

Codes not listed are reserved; senders must not use them; receivers must discard and log.

---

## 3. Timing and Synchronization

### 3.1 20 Hz Tick Structure

The Layer 1 control loop runs at 20 Hz (T_tick = 50 ms). The tick master is the node; struts derive their slot phase from module ID. All timing below is relative to tick boundary t = 0 as declared by the node.

```
t = 0 ms              t = 50 ms
│                           │
│◄───────── 50 ms tick ────►│
│                           │
│ STRUT TX PHASE            │ (TDMA — see §3.2)
│ [slot 0 ] strut_id=0      │
│  ├─ TX: 30B @ 115200 baud │ (~2.6 ms TX time per slot)
│  └─ node IR RX             │
│ [slot 1 ] strut_id=1      │
│  ...                      │
│ [slot 11] strut_id=11     │
│                           │
│ t ≈ 42 ms                 │
│ NODE INFERENCE WINDOW     │ (~5 ms budget for CTDE/MAPPO)
│  ├─ aggregate 16-d obs    │
│  ├─ run policy forward    │
│  └─ pack 28B broadcast    │
│                           │
│ t ≈ 47 ms                 │
│ NODE TX (broadcast)       │ (~2.4 ms for 28B @ 115200 baud)
│  └─ all struts RX action  │
│                           │
│ t ≈ 49.4 ms               │
│ MARGIN / OVERRUN DETECT   │ (~0.6 ms watchdog window)
│                           │
│ t = 50 ms: next tick      │
```

**Timing budget (P0.2, ≤12 struts per node, UART 115200 baud 8N1):**

| Phase | Duration | Notes |
|-------|----------|-------|
| Strut TX window (per strut) | ~2.6 ms | 30 bytes × 10 bits / 115200 |
| TDMA slot (per strut) | 3.5 ms | 2.6 ms TX + 0.9 ms guard |
| Total strut TX phase (12 struts) | 42 ms | 12 × 3.5 ms |
| Node inference | ≤5 ms | CTDE/MAPPO on ESP32-S3 |
| Node broadcast TX | ~2.4 ms | 28 bytes × 10 bits / 115200 |
| Tick margin | ~0.6 ms | Watchdog detects overrun |

**Overrun handling:** If node inference exceeds budget and total tick duration > 52 ms for two consecutive ticks, the node broadcasts `quorum_active = 0` and logs a timing fault. Struts freeze on `quorum_active = 0` sustained >2 s (see §5).

**Clock synchronization:** No hardware clock sync in P0.2. Tick counter (`tick` field) is a monotonic software counter on each module; counters are independently maintained and compared only for age checks (max ±1 tick tolerance). A shared time-base via NTP or PPS is deferred to P5.x.

### 3.2 TDMA Slot Allocation

Layer 1 uses TDMA to prevent IR collision between struts transmitting on the same node's IR RX. Slot assignment is deterministic from module ID, requiring no coordination.

```
slot_start(strut_id) = strut_id × T_slot_ms
T_slot_ms = 3.5 ms   (P0.2 nominal; measure and calibrate in P4.7 — see OPEN-003)
```

**Slot table for P0.2 (strut IDs 0–11):**

| Strut ID | Slot Start (ms) | TX Window End (ms) | Guard End (ms) |
|----------|-----------------|--------------------|----------------|
| 0 | 0.0 | 2.6 | 3.5 |
| 1 | 3.5 | 6.1 | 7.0 |
| 2 | 7.0 | 9.6 | 10.5 |
| 3 | 10.5 | 13.1 | 14.0 |
| 4 | 14.0 | 16.6 | 17.5 |
| 5 | 17.5 | 20.1 | 21.0 |
| 6 | 21.0 | 23.6 | 24.5 |
| 7 | 24.5 | 27.1 | 28.0 |
| 8 | 28.0 | 30.6 | 31.5 |
| 9 | 31.5 | 34.1 | 35.0 |
| 10 | 35.0 | 37.6 | 38.5 |
| 11 | 38.5 | 41.1 | 42.0 |

Node inference begins at t = 42.0 ms; node TX begins at t ≈ 47.0 ms.

**Notes:**
- Not all 12 strut slots may be occupied in a given topology; unoccupied slots are idle.
- A node that connects to ≤4 struts (typical for P0.2 tree topology) uses only the relevant slots; unused slots remain silent.
- Struts on different nodes do not share an IR RX bus and do not collide regardless of slot assignment.
- **[OPEN-003]** Guard time of 0.9 ms is estimated; measure actual IR settling time and UART turnaround in P4.7 to confirm no inter-slot bleed.

---

## 4. Bandwidth Analysis

### 4.1 Layer 1 Per-Link and Aggregate

| Metric | Value | Derivation |
|--------|-------|------------|
| Raw UART rate | 115,200 baud | 8N1, hardware UART |
| Strut → Node payload per tick | 30 bytes = 240 bits | 20 Hz × 240 bits = 4,800 bps raw |
| Node → Struts payload per tick | 28 bytes = 224 bits | 20 Hz × 224 bits = 4,480 bps raw |
| Round-trip per link | 464 bits per tick | — |
| Effective payload bps (headers excluded) | ~1,200 bps | 16-byte payload in 30-byte frame |
| Links in P0.2 (20 modules, tree) | ≤20 | One IR link per dock interface |
| Aggregate Layer 1 bandwidth | ~24 kbps payload | 20 links × 1.2 kbps |
| Total bus utilization (12-strut worst case) | ~84% | 42 ms TX / 50 ms tick |

### 4.2 Layer 2 Sustained and Peak

| Traffic Class | Packet Size | Rate | Average bps | Peak bps |
|---------------|------------|------|-------------|----------|
| Goal diffusion | 300 bytes | ≤0.5 Hz (2 s min interval) | ~1,200 bps | ~2,400 bps |
| Safety broadcast (ARM/E-STOP) | 16 bytes | Event-driven | ~0 bps sustained | ~1,280 bps burst |
| Telemetry uplink | 8–20 bytes | ~1 Hz per module (20 modules) | ~3,200 bps | ~6,400 bps |
| **Total Layer 2** | — | — | **<10 kbps sustained** | **<50 kbps peak** |

ESP-NOW raw PHY: 1 Mbps (802.11 OFDM); effective application bandwidth well below saturation in P0.2.

---

## 5. Activation and Quorum Protocol

### 5.1 State Machine

```
         power-on
              │
              ▼
          ┌──────┐
          │ IDLE │  ◄────────── E_STOP received
          └──┬───┘              or quorum loss >2 s
             │
             │ ARM (0x11, param0=0x01)
             │ authenticated + tick-fresh
             ▼
          ┌───────┐
          │ ARMED │  Motors powered; awaiting first goal diffusion
          └──┬────┘
             │
             │ GOAL_DIFFUSION received
             │ AND quorum_active = 0x01
             ▼
          ┌────────┐
          │ ACTIVE │  Normal 20 Hz control loop running
          └──┬─────┘
             │◄────────────────┐
             │                 │ Goal update (new GOAL_DIFFUSION)
             │                 │ → update goal_version, continue
             │
             │ Any of:
             │  • E_STOP (0x12) received
             │  • ARM disarm (0x11, param0=0x00)
             │  • quorum_active=0 sustained >2 s
             │  • Vbat < V_critical (OPEN-004)
             ▼
          ┌─────────┐
          │ E_STOP  │  All motor drivers: nSLEEP = LOW within 5 ms
          └────┬────┘  All Layer 1 TX continues (telemetry / health)
               │
               │ Manual ARM disarm + ARM re-arm sequence
               ▼
           back to IDLE
```

### 5.2 Quorum Rules

| Condition | Action | Timeout |
|-----------|--------|---------|
| ≥80% of node's connected struts reported this tick | `quorum_active = 0x01` | Per-tick |
| <80% of connected struts | `quorum_active = 0x00` | Per-tick |
| `quorum_active = 0x00` sustained | Node broadcasts freeze advisory on Layer 2 | >2 s |
| No Layer 2 goal diffusion received | Node enters QUORUM_HOLD, struts freeze | >4 s |
| Strut misses >2 consecutive node broadcasts | Strut enters local SAFE_HOLD, holds last position | — |

### 5.3 NFC Fallback (Rev B / R1b Only)

When ESP-NOW Layer 2 is unavailable or a new module joins a powered swarm, NFC provides a backup channel for:
- Module ID assignment (unicast, tap-to-configure)
- ARM/DISARM commands (proximity-only, requires physical access)
- Goal vector seeding (tap phone/orchestrator to any node)

NFC in R1b is a fallback only; it does not participate in the 20 Hz control loop. Protocol and tag format: **[OPEN-005 — define NFC provisioning protocol in R1b design phase]**.

---

## 6. Electrical Interfaces

### 6.1 Strut Module

#### 6.1.1 Block Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    STRUT MODULE (P0.2)                       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  ESP32-S3 Dual-Core LX7 @ 240 MHz                   │    │
│  │  8 MB PSRAM, native ESP-NOW radio                   │    │
│  ├──────────────────────────────────────────────────────┤    │
│  │ UART0 (debug) ──────────────► [USB-Serial / J1]     │    │
│  │ SPI (MOSI/MISO/CLK/CS) ─────► ICM-42688 IMU         │    │
│  │ I2C Bus 0 (SDA/SCL) ────────► MAX17048 Battery Gauge│    │
│  │ UART1 (hardware) ───────────► IR Transceiver A      │    │
│  │ UART2 (SW bit-bang) ────────► IR Transceiver B      │    │
│  │ GPIO + PWM (4 lines) ───────► DRV8833 #1 (Motor A)  │    │
│  │ GPIO + PWM (4 lines) ───────► DRV8833 #2 (Motor B)  │    │
│  │ GPIO (Priority ISR) ────────► e-stop watchdog        │    │
│  │ ADC (GPIO 11) ──────────────► Vbat sense (R-divider) │    │
│  └──────────┬───────────────────────┬───────────────────┘    │
│             │                       │                         │
│  ┌──────────▼────────┐   ┌──────────▼────────┐               │
│  │   DRV8833 #1      │   │   DRV8833 #2      │               │
│  ├───────────────────┤   ├───────────────────┤               │
│  │ IN1/IN2 (dir)     │   │ IN1/IN2 (dir)     │               │
│  │ PWM (speed)       │   │ PWM (speed)       │               │
│  │ nSLEEP ◄──────────┼───┼── GPIO (e-stop)   │               │
│  │ nFAULT ──────────►│   │ nFAULT ──────────►│ → MCU ADC/GPIO│
│  │ ISENSE ──────────►│   │ ISENSE ──────────►│ [optional]    │
│  │ Imax = 1.0 A (HW) │   │ Imax = 1.0 A (HW) │               │
│  └──────────┬────────┘   └──────────┬────────┘               │
│             │                       │                         │
│  ┌──────────▼────────┐   ┌──────────▼────────┐               │
│  │  Gimbal Motor A   │   │  Gimbal Motor B   │               │
│  │  Micro GM (Pan)   │   │  Micro GM (Tilt)  │               │
│  │  ≥0.8 N·m         │   │  ≥0.8 N·m         │               │
│  └───────────────────┘   └───────────────────┘               │
│        [gimbal spec §P3.2 — OPEN-006]                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ ICM-42688 6-Axis IMU (SPI)                           │    │
│  │ Accelerometer: ±16 g @ 16-bit (int8 quantized L1)   │    │
│  │ Gyroscope: ±2000 °/s @ 16-bit                        │    │
│  │ ODR: 1 kHz internal; decimated to 20 Hz for L1      │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ MAX17048 1S Li-ion Fuel Gauge (I2C addr 0x36)        │    │
│  │ Reports: Vbat (1 mV LSB), SoC (1% LSB), AlertB pin  │    │
│  │ Alert threshold: configurable; default 15% SoC       │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 1S Li-ion 18650 Cell (3.6–4.2 V nominal)             │    │
│  │ Capacity: ~2600 mAh (Keeppower / Sanyo class)        │    │
│  │ Peak draw: 3.5 W @ 3.7 V ≈ 950 mA (full gimbal)     │    │
│  │ Average: 1.5 W @ 3.7 V ≈ 405 mA (idle + sensor)     │    │
│  │ Estimated runtime @ 1.5 W avg: ~8–10 h              │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Charging Interface: 4× Gold-Plated Pads (midbody)    │    │
│  │ Pad 1: V+ (5 V from charger)                         │    │
│  │ Pad 2: GND                                           │    │
│  │ Pad 3: ID (not used in P0.2; reserved)               │    │
│  │ Pad 4: GND (redundant for mechanical stability)      │    │
│  │ Charger IC: TP4056 or equivalent 1S LiPo charger    │    │
│  │ Charge rate: 500 mA CC/CV default (configurable)    │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ IR Transceiver Pair A (Connector End A)              │    │
│  │ ├─ TX: IR LED, ~940 nm, UART1 PWM carrier mod.      │    │
│  │ ├─ RX: Phototransistor (visible-blocking filter)     │    │
│  │ ├─ Interface: UART1 (hardware), 115200 baud 8N1      │    │
│  │ └─ Range: ~1 m at dock face (OPEN-007 — measure P4.2)│    │
│  │                                                      │    │
│  │ IR Transceiver Pair B (Connector End B)              │    │
│  │ ├─ TX: IR LED, ~940 nm, UART2 (SW bit-bang) carrier │    │
│  │ ├─ RX: Phototransistor (visible-blocking filter)     │    │
│  │ ├─ Interface: UART2 (GPIO bit-bang), 115200 baud 8N1 │    │
│  │ └─ Range: ~1 m at dock face                         │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

#### 6.1.2 Strut Module Pin Assignment (ESP32-S3)

| GPIO | Function | Direction | Peripheral | Notes |
|------|----------|-----------|------------|-------|
| 0 | BOOT | IN | — | Pull-up; low at reset for download mode |
| 1 | UART0 TX | OUT | USB-Serial debug | |
| 2 | UART0 RX | IN | USB-Serial debug | |
| 3 | SPI MOSI | OUT | ICM-42688 | |
| 4 | SPI MISO | IN | ICM-42688 | |
| 5 | SPI CLK | OUT | ICM-42688 | |
| 6 | SPI CS | OUT | ICM-42688 | Active low |
| 7 | ICM-42688 INT | IN | IMU data-ready ISR | |
| 8 | I2C SDA | I/O | MAX17048 | 4.7 kΩ pull-up |
| 9 | I2C SCL | OUT | MAX17048 | 4.7 kΩ pull-up |
| 10 | MAX17048 ALRT | IN | Fuel gauge alert ISR | Active low |
| 11 | ADC Vbat | IN (ADC) | R-divider Vbat sense | 1:2 divider; Vbat = ADC × 2 |
| 12 | DRV8833 #1 IN1 | OUT | Motor A dir | |
| 13 | DRV8833 #1 IN2 | OUT | Motor A dir | |
| 14 | DRV8833 #1 PWM | OUT (LEDC) | Motor A speed | |
| 15 | DRV8833 #1 nFAULT | IN | Motor A fault | Active low; ISR |
| 16 | DRV8833 #2 IN1 | OUT | Motor B dir | |
| 17 | DRV8833 #2 IN2 | OUT | Motor B dir | |
| 18 | DRV8833 #2 PWM | OUT (LEDC) | Motor B speed | |
| 19 | DRV8833 #2 nFAULT | IN | Motor B fault | Active low; ISR |
| 20 | nSLEEP (shared) | OUT | Both DRV8833 | Low = coast; e-stop ties to this pin |
| 21 | UART1 TX | OUT | IR Transceiver A TX | |
| 22 | UART1 RX | IN | IR Transceiver A RX | |
| 23 | UART2 TX (SW) | OUT | IR Transceiver B TX | Bit-bang |
| 24 | UART2 RX (SW) | IN | IR Transceiver B RX | Bit-bang |
| 38 | E-STOP watchdog | IN (ISR) | External safety line | Priority ISR; deasserts nSLEEP |
| 39–40 | RF (ESP-NOW) | — | 2.4 GHz antenna | Internal trace antenna |

*Unassigned GPIOs: reserved; do not connect in P0.2.*

#### 6.1.3 Strut Power Budget

| Load | Average (mA @ 3.7 V) | Peak (mA @ 3.7 V) | Notes |
|------|-----------------------|--------------------|-------|
| ESP32-S3 active (WiFi/BT off, ESP-NOW) | 100 mA | 250 mA | ESP-NOW TX bursts |
| ICM-42688 IMU | 2 mA | 2 mA | |
| MAX17048 Fuel Gauge | 0.05 mA | 0.05 mA | |
| IR TX LED (duty ~5%) | 5 mA avg | 100 mA peak | 940 nm, 50 Ω series; duty per TDMA slot |
| DRV8833 #1 + #2 (idle) | 1 mA | — | nSLEEP held high |
| Gimbal Motor A + B (loaded) | 300 mA avg | 600 mA peak | Full stall both motors |
| **Total** | **~408 mA avg** | **~952 mA peak** | |
| **Power** | **~1.51 W avg** | **~3.52 W peak** | |
| **Runtime (2600 mAh)** | **~6.4 h** (net) | — | Derated 0.85 for Peukert + converter eff. |

---

### 6.2 Node Module

#### 6.2.1 Block Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    NODE MODULE (P0.2)                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  ESP32-S3 Dual-Core LX7 @ 240 MHz                   │    │
│  │  8 MB PSRAM (CTDE/MAPPO inference buffers)          │    │
│  │  native ESP-NOW radio                               │    │
│  ├──────────────────────────────────────────────────────┤    │
│  │ UART0 (debug) ──────────────► [USB-Serial / J1]     │    │
│  │ SPI (MOSI/MISO/CLK/CS) ─────► ICM-42688 IMU (opt.) │    │
│  │ I2C Bus 0 (SDA/SCL) ────────► MAX17048 Battery Gauge│    │
│  │ UART1 (hardware) ───────────► IR Port 0 (dock face 0)│   │
│  │ UART2 (hardware) ───────────► IR Port 1 (dock face 1)│   │
│  │ UART3 (SW bit-bang) ────────► IR Port 2 (dock face 2)│   │
│  │ UART4 (SW bit-bang) ────────► IR Port 3 (dock face 3)│   │
│  │ GPIO (Priority ISR) ────────► e-stop watchdog        │    │
│  │ ADC ────────────────────────► Vbat sense             │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  IR Ports 0–3: each is one full-duplex IR Transceiver Pair  │
│  (same component as strut; facing outward on each dock face) │
│  Max 4 strut connections per node in P0.2 (typical: 1–2)    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 1S Li-ion 18650 Cell (same spec as strut)            │    │
│  │ Average draw (inference): ~2.0 W @ 3.7 V ≈ 540 mA   │    │
│  │ No DRV8833 in Rev A node (structural hub, unpowered) │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Charging Interface: same 4-pad scheme as strut       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

#### 6.2.2 Node Module Pin Assignment (ESP32-S3)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| 0 | BOOT | IN | Same as strut |
| 1–2 | UART0 TX/RX | OUT/IN | Debug |
| 8–9 | I2C SDA/SCL | I/O | MAX17048 |
| 10 | MAX17048 ALRT | IN | |
| 11 | ADC Vbat | IN | |
| 21–22 | UART1 TX/RX | OUT/IN | IR Port 0 (hw) |
| 23–24 | UART2 TX/RX | OUT/IN | IR Port 1 (hw) |
| 25–26 | UART3 TX/RX (SW) | OUT/IN | IR Port 2 (bit-bang) |
| 27–28 | UART4 TX/RX (SW) | OUT/IN | IR Port 3 (bit-bang) |
| 38 | E-STOP watchdog | IN (ISR) | Priority ISR |
| 39–40 | RF (ESP-NOW) | — | |

*Nodes in Rev B may add motor drivers if reconfiguration joints are required — deferred to plan revision post-P3.2 gimbal spec.*

#### 6.2.3 Node Power Budget

| Load | Average (mA @ 3.7 V) | Peak (mA @ 3.7 V) |
|------|-----------------------|--------------------|
| ESP32-S3 + PSRAM (inference active) | 200 mA | 350 mA |
| ICM-42688 (if populated) | 2 mA | 2 mA |
| 4× IR TX LEDs (TDMA duty) | 15 mA avg | 100 mA peak |
| MAX17048 | 0.05 mA | 0.05 mA |
| **Total** | **~217 mA avg** | **~452 mA peak** |
| **Runtime (2600 mAh)** | **~12 h** | — |

---

### 6.3 Inter-Module Connector Interface

#### 6.3.1 Physical Connector

| Parameter | Value | Notes |
|-----------|-------|-------|
| Connector type | Multi-directional magnetic snap | 26 indexed positions (`connector_id` 0–25, §2.1.1) |
| Mating faces | Flat with optical window + electrical contacts | IR window: 5 mm clear aperture, centered on face |
| Alignment | Passive — mechanical key + magnet bias | ±5° angular tolerance |
| Retention force | TBD | **[OPEN-008 — characterize in P3.x]** |
| Separation force | TBD | **[OPEN-008]** |
| Electrical contacts at connector | None in P0.2 (IR only) | Power sharing deferred — **[OPEN-009]** |
| NFC antenna at connector | No (Rev A); Yes (Rev B / R1b) | PN532 or equivalent; tap-range ≤5 cm |

#### 6.3.2 IR Optical Interface at Connector

| Parameter | Value |
|-----------|-------|
| Wavelength | 940 nm nominal |
| TX peak current | 100 mA (with 50 Ω series resistor at 3.7 V) |
| Modulation | UART 115200 baud NRZ (no carrier); signal-on = IR off for idle state |
| RX component | Phototransistor with visible-light blocking filter |
| Receive distance | ~1 m open air; ≤5 mm at dock face (direct coupling) — **[OPEN-007]** |
| Ambient rejection | Filter Tc > 800 nm; enclosure mechanical shield around dock window |
| Connector IR clearance | ≥3 mm air gap at dock interface to limit cross-coupling |

#### 6.3.3 `connector_id` Encoding

`connector_id` (u8, 0–25) encodes the dock face on the originating module as a cube-face-extended scheme:

| ID | Face / Position |
|----|----------------|
| 0 | +X (End A) |
| 1 | −X (End B) |
| 2 | +Y |
| 3 | −Y |
| 4 | +Z |
| 5 | −Z |
| 6–25 | Extended positions (non-rectilinear edges/diagonals, P0.2 unused) |

Full 26-position encoding specification: **[OPEN-010 — define extended positions in P3.x connector spec]**.

---

## 7. Safety-Critical Paths

### 7.1 E-STOP Signal Chain

The e-stop path must be the highest-priority interrupt chain on each module. Two independent paths exist:

| Path | Mechanism | Max Latency | Trigger |
|------|-----------|-------------|---------|
| **Primary** — Layer 2 software | ESP-NOW E_STOP packet → FreeRTOS high-priority queue → motor driver nSLEEP low | ≤5 ms | Operator or orchestrator |
| **Secondary** — Hardware GPIO | External e-stop line → GPIO ISR (priority 5, highest) → nSLEEP low via direct GPIO write | <1 ms | Hardwired safety loop |
| **Tertiary** — Quorum watchdog | FreeRTOS task: `quorum_active=0` sustained >2 s → soft freeze | ≤2 s | Loss of inter-module comms |
| **Quaternary** — Battery undervoltage | MAX17048 AlertB → ISR → motor freeze | <10 ms | Vbat < V_critical |

`V_critical` (battery cutoff): **[OPEN-004 — define threshold in P4.x power characterization]**.

### 7.2 DRV8833 Fault Monitoring

Each DRV8833 motor driver exposes `nFAULT` (active low):

- nFAULT driven low indicates: overcurrent (OCP) or thermal shutdown (TSD).
- nFAULT ISR handler must: (1) coast both outputs (IN1=IN2=0), (2) log fault code via telemetry 0x04, (3) hold motor disabled for ≥500 ms before auto-retry (one retry only; escalate to full e-stop on second fault).
- nSLEEP being held low (e-stop) places both outputs in high-impedance; nFAULT will be low during sleep.

### 7.3 HMAC Failure Handling

| Event | Required action |
|-------|----------------|
| Layer 2 packet fails HMAC | Discard silently; increment `rx_hmac_fail` counter; do NOT act on payload |
| 3 consecutive HMAC failures from same source | Log event; send telemetry alert; flag orchestrator |
| HMAC failure on E_STOP packet | **Log and discard** — do not execute unauthenticated safety commands |
| HMAC failure on ARM packet | **Log and discard** |

### 7.4 Watchdog Timers

| Watchdog | Period | Action on Expiry |
|----------|--------|-----------------|
| FreeRTOS task watchdog (Layer 1 tick task) | 150 ms (3 ticks) | Reboot MCU; log to flash |
| Layer 2 ESP-NOW receive watchdog | 4 s | Enter QUORUM_HOLD; freeze struts |
| DRV8833 nFAULT poll | 100 ms | Check nFAULT line; log if asserted |
| Hardware WDT (ESP32-S3 RWDT) | 5 s | Full chip reset; re-enter IDLE state |

---

## 8. Hardware Revision Notes

### 8.1 Revision A (Rev A) — Devkit-Based Prototype

| Aspect | Rev A Implementation |
|--------|---------------------|
| MCU board | ESP32-S3 DevKit-C (38-pin) |
| Form factor | Hand-assembled on proto PCB / perfboard; no custom PCB |
| IR transceiver | Discrete LED + phototransistor; through-hole component |
| Motor driver | DRV8833 breakout module (TI EVM or equivalent) |
| Battery | Bare 18650 in holder with leads; no integrated BMS |
| Charging | External TP4056 module; charge pads are test-point wires |
| NFC | **Not present** |
| Dimensions | Non-standardized; module outline TBD |
| Purpose | Firmware + algorithm validation; not representative of final mechanical form |

### 8.2 Revision B / R1b — Custom PCB

| Aspect | Rev B / R1b Target |
|--------|-------------------|
| MCU | ESP32-S3 (same die; integrated antenna or external; TBD) |
| Form factor | Custom 4-layer PCB; mechanical profile defined by gimbal/dock spec (§P3.2) |
| IR transceiver | Integrated SMD LED (SFH 4556 or equivalent 940 nm) + SMD phototransistor |
| Motor driver | DRV8833 in QFN package; integrated on PCB |
| Battery | Integrated 1S Li-ion with on-board BMS and over-temperature protection |
| Charging | On-board TP4056 or MCP73831; 4-pad charging interface compliant with dock spec |
| NFC | PN532 (or ST25R3916) + PCB trace antenna; connector-face placement; **[OPEN-005]** |
| Dimensions | Per master plan Appendix A (frozen after P3.2 DR) |
| Purpose | First field-deployable hardware; target for P4.x calibration measurements |

### 8.3 Compatibility

Layer 1 and Layer 2 protocols are identical between Rev A and Rev B. Rev A and Rev B modules may coexist in the same swarm during transition. Rev A nodes cannot act as NFC provisioning targets (capability absent); all other swarm functions are compatible.

---

## 9. Open Items

All `[OPEN]`, `[PLACEHOLDER]`, and TBD items from Sections 1–8 are consolidated here. Each item is numbered, assigned a responsible phase, and back-referenced.

| # | Item | Responsible Phase | Reference |
|---|------|-------------------|-----------|
| OPEN-001 | CRC-16 byte coverage and field placement in Layer 1 messages (strut→node and node→struts). Current header is CRC of bytes 0–9 (strut) / 0–6 (node); confirm with P4.7 link measurements that this covers all mutable-before-TX fields. | P4.7 | §2.1.1, §2.1.3 |
| OPEN-002 | HMAC-SHA256 truncation scheme for Layer 2 packets. Current spec uses 32-bit truncation for goal/safety and 16-bit truncation for node broadcast. Derive final truncation length and key management approach (per-swarm pre-shared key storage, rotation policy). | P4.7 | §2.1.3, §2.2.1, §2.2.2 |
| OPEN-003 | TDMA guard time calibration. Current 0.9 ms guard is an estimate. Measure actual IR LED rise/fall time, UART turnaround, and phototransistor settling in P4.7 bench tests. Update T_slot_ms accordingly. | P4.7 | §3.2 |
| OPEN-004 | Battery undervoltage cutoff threshold V_critical. Define threshold (nominally ~3.2 V for 1S Li-ion) in P4.x power characterization; set MAX17048 alert register and add to Appendix A frozen parameters. | P4.x | §7.1 |
| OPEN-005 | NFC provisioning protocol for R1b. Define NFC NDEF record structure for: module ID assignment, ARM/DISARM commands, goal vector seeding. Select NFC controller IC. | R1b design phase | §5.3, §8.2 |
| OPEN-006 | Gimbal motor final selection. Current spec: ≥0.8 N·m micro gimbal motor. Final part number, encoder type (if any), winding resistance, and stall current to be locked in P3.2 DR. Update DRV8833 current limit after selection. | P3.2 | §6.1.1 |
| OPEN-007 | IR range measurement at dock interface. Estimate: ~1 m open air; dock face coupling (≤5 mm gap) expected to be reliable. Measure SNR vs. distance and ambient light levels in P4.2 bench tests. | P4.2 | §6.1.1, §6.3.2 |
| OPEN-008 | Connector retention and separation force characterization. Target values TBD pending dock mechanism selection in P3.x. Add to Appendix A after P3.x DR. | P3.x | §6.3.1 |
| OPEN-009 | Power sharing at connector interface. Rev A: no electrical contacts at dock (IR only). Rev B scope: determine if V_bat pass-through to docked neighbor is required for swarm lifetime extension. If yes, add connector power pins to §6.3 and safety analysis to §7. | P3.x → P5.x | §6.3.1 |
| OPEN-010 | Extended connector_id positions 6–25. Define the full 26-position encoding for non-rectilinear dock faces as the module geometry is finalized in P3.x connector spec. | P3.x | §6.3.3 |
| OPEN-011 | Node motor drivers. Rev A node has no DRV8833 (structural hub only). If reconfiguration joints require actuated nodes, add DRV8833 to node BOM and update §6.2.1, §7.1 accordingly post-P3.2 DR. | P3.2 (conditional) | §6.2.1 |
| OPEN-012 | Multi-packet goal diffusion. P0.2: single 300-byte packet. Future: if goal vector exceeds ESP-NOW MTU (250 bytes for application payload) or dimensionality is increased, implement reassembly using `total_packets`/`packet_index` fields already reserved in §2.2.1. | P5.x | §2.2.1 |
| OPEN-013 | Tick clock synchronization. P0.2 uses independent software counters with ±1 tick tolerance for age checks. If cross-module tick correlation is required for distributed observation fusion, add PPS or NTP-disciplined sync in P5.x. | P5.x | §3.1 |

---

## Appendix A — Frozen Parameters (from Master Plan §0.0 / Appendix A)

The following parameters are frozen for P0.2. Changes require a formal plan revision with DR board sign-off. Parameters annotated **[pending]** will be frozen upon completion of the referenced open item.

### A.1 Control Loop

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| Tick rate | 20 | Hz | Layer 1 period = 50 ms |
| UART baud rate (Layer 1) | 115,200 | baud | 8N1, no flow control |
| TDMA slot duration | 3.5 | ms | Nominal; calibrate per OPEN-003 |
| Node inference budget | 5 | ms | Hard limit within tick |
| Max tick overrun before fault | 2 | ticks | Triggers watchdog reboot |

### A.2 Signal Encoding

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| Observation vector dimension | 16 | d | int8 quantized |
| Action vector dimension | 16 | d | int8 quantized |
| Goal vector dimension | 128 | d | float16 (IEEE 754 half-precision) |
| Layer 1 CRC polynomial | 0x1021 | — | CCITT-16 |
| Layer 1 CRC initial value | 0xFFFF | — | Standard CCITT init |
| Layer 2 HMAC algorithm | SHA-256 | — | Truncated to 32 bits |

### A.3 System Topology

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| Max modules (P0.2) | 20 | — | 12 struts + 8 nodes |
| Max strut ID | 11 | — | Struts occupy IDs 0–11 |
| Max node ID | 19 | — | Nodes occupy IDs 12–19 |
| Max dock positions per module | 26 | — | connector_id 0–25 |
| Quorum threshold | 80 | % | Fraction of connected struts that must report per tick |
| Quorum freeze timeout | 2 | s | Duration quorum_active=0 before strut freeze |
| Goal diffusion max interval | 2 | s | Layer 2 keepalive; enter QUORUM_HOLD at 4 s |

### A.4 Electrical

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| MCU | ESP32-S3 | — | Dual-core LX7, 240 MHz |
| MCU PSRAM | 8 | MB | Inference buffers |
| IMU | ICM-42688 | — | 6-axis; SPI |
| Fuel gauge | MAX17048 | — | I2C addr 0x36 |
| Motor driver | DRV8833 | — | Per strut; 2× per module |
| Motor current limit (HW) | 1.0 | A | DRV8833 ISENSE Rset |
| Motor torque minimum | 0.8 | N·m | Gimbal motor spec floor; OPEN-006 |
| IR wavelength | 940 | nm | Nominal |
| IR range (dock) | 1 | m | Estimated; OPEN-007 |
| Battery chemistry | 1S Li-ion | — | 18650 cell |
| Battery nominal voltage | 3.7 | V | |
| Battery capacity (design) | 2600 | mAh | |
| Charge interface | 4-pad gold-plated | — | V+/GND/ID/GND |
| V_critical (cutoff) | TBD | V | **[pending OPEN-004]** |
| Connector retention force | TBD | N | **[pending OPEN-008]** |
