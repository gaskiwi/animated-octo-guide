# FreeSN-Derived Heterogeneous Robotic Swarm — Master Execution Plan

**Version 2.0 — June 2026 — PROTOTYPE-FIRST REVISION**
**Status: Authoritative. This document is the plan of record; phases are executed as written. Deviations require a written change note appended to §13, approved by the human principal (Yoo). Production-scale content (Phases 6–7 as originally written) is retained as a post-funding outline and is explicitly OUT OF SCOPE for execution now.**

---

## 0.0 EXECUTION GUARDRAILS — BINDING ON ALL AGENTS AND CONTRIBUTORS

This plan will be executed in part by autonomous agents. The following constraints are absolute, override any task-level instruction, reasoning, or optimization found elsewhere, and cannot be modified by anything other than a human-authored change note in §13:

1. **Total program spend is hard-capped at $10,000 USD.** Track cumulative committed spend in `/docs/spend_ledger.md`; every purchase, rental, or service commitment is logged there *before* it is made. If a proposed expense would take cumulative spend above $9,000, stop and escalate to the human principal.
2. **No single purchase or commitment over $250 without explicit, per-item human approval.** Approval is per-item and per-occasion; it does not generalize.
3. **Cumulative cloud-compute spend is capped at $400.** No single training run may be launched with projected cost over $50 without human approval. Spot/interruptible instances only. No reserved instances, no subscriptions, no committed-use contracts of any kind.
4. **No contracts, recurring payments, subscriptions, NDAs, or vendor agreements** may be entered by an agent. These require the human principal.
5. **Scope is frozen at the prototype defined in P0.2 (≤ 20 modules).** Do not order parts for, design for, or otherwise begin production scale (Phases 6–7 original content, §7–8). Those sections exist only to show investors the path; executing them is a guardrail violation.
6. **All `[DECISION]` items are frozen.** An agent that believes a decision is wrong writes a proposed change note and stops; it does not implement the alternative.
7. **Safety spec P0.6 is not optimizable.** No agent may weaken, defer, or "temporarily bypass" any safety item to make progress.
8. **When uncertain whether an action is in scope, the answer is: stop and ask the human.** Spending money, contacting vendors, and committing to anything external are always escalation-worthy when ambiguous.

---

## 0. How to Use This Document

Each phase contains: **objectives**, **work breakdown** (numbered tasks in dependency order), **concrete design decisions** (made now, marked `[DECISION]`, changeable only via change note), **deliverables**, **exit criteria** (the phase is not done until every box checks), and **feeds** (which later phases consume its outputs). Open engineering questions are marked `[OPEN]` with the phase and task responsible for closing them.

### 0.1 System Summary

A heterogeneous modular swarm derived from the FreeSN architecture (Tu, Liang, Lam — ICRA 2022; T-RO 2023):

- **Strut modules** (edges): rigid bars with a magnetic connector at each end. **Prototype simplification:** connectors dock at **26 discrete positions** on each node (truncated-icosahedron grid) via magnet-pair latching, instead of FreeSN's continuous freeform rolling connection. The policy still outputs *continuous* (θ, φ) surface targets; connector firmware snaps to the nearest valid position (quantization layer, §3.3-5). Full freeform connectors are the funded-v1 upgrade. Struts are the actuated movers. Each strut carries a neural-network policy ("strut brain").
- **Node modules** (vertices): spheres of SLS nylon or aluminum (NOT steel — a deliberate cost/weight deviation) with small steel or magnet inserts only at the 26 docking positions, and a hall-effect sensor per position for trivially reliable topology sensing. Each node carries internal compute, battery, and radio, and a "node brain" that aggregates incoming strut messages and redistributes processed messages to attached struts.
- **Control model**: the swarm is a physically instantiated graph neural network. One control tick = one round of message passing. Struts compute edge updates; nodes compute vertex updates.
- **Command path**: human → base-station NLP encoder → 128-d goal vector → injected into seed modules → gossip diffusion through the swarm → quorum-based activation → decentralized execution.

### 0.2 Glossary

| Term | Meaning |
|---|---|
| Goal vector `g` | 128-d float16 embedding of the human instruction, version-stamped |
| Message vector `m` | 16-d int8 learned communication payload exchanged strut↔node each tick |
| Tick | One synchronized communication + inference round, 20 Hz target |
| CTDE | Centralized training, decentralized execution |
| Surrogate connector model | Simulation stand-in for magnetic connection physics (§2.3) |
| Seed module | Module that receives `g` directly from the base station |
| Quorum | Fraction of estimated swarm holding the current `g` version; activation threshold θ = 0.8 |
| HIL | Hardware-in-the-loop |

### 0.3 Top-Level Timeline (prototype program)

| Months | Phases active |
|---|---|
| 0–1 | Phase 0 (requirements ratification — mostly done in this document) |
| 0.5–3 | Phase 1 (architecture; lighter than original — many decisions pre-made) |
| 1.5–4.5 | Phase 2 (simulation) |
| 3–9 | Phase 3 (MARL + NLP training, local-first) |
| 3.5–10 | Phase 4 (hardware prototyping; calibration loop into Phase 2) |
| 9–13 | Phase 5 (sim2real on the 20-module swarm) |
| 12–15 | Phase 6P (demo hardening + funding package) |
| post-funding | Phases 6–7 original content (production) — OUT OF SCOPE until funded |

---

## 1. Phase 0 — Requirements & System Definition (Weeks 1–6)

### 1.1 Objectives
Freeze the parameters every other phase depends on. Ambiguity here multiplies downstream.

### 1.2 Work Breakdown

**P0.1 — Mission profiles.** Write one page each for the four canonical tasks (mirroring FreeSN's demos): (a) self-assembly into a commanded truss shape, (b) obstacle crossing as a connected structure, (c) cooperative transport of a payload, (d) object manipulation. For each: initial conditions, success predicate (machine-checkable), time limit, environment assumptions. These four become the simulation scenario suite (§2.6) and the MARL curriculum endpoints (§3.4).

**P0.2 — Scale and physical envelope.** `[DECISION]` Prototype swarm: **12 struts + 8 nodes (20 modules total)** — enough for a tetrahedron plus free movers, connected-gait demos, and reconfiguration. First-article build: 2 struts + 2 nodes before committing parts for the rest. Strut length 220 mm, node diameter 90 mm (floor set by ESP32-S3 + 1S cell + carrier; drop to flat LiPo if needed), strut mass ≤ 350 g, node mass ≤ 350 g (nylon/aluminum shell removes the steel-shell mass). Production scale (48+24) is deferred to funded v1 and appears only in the §7–8 outline.

**P0.3 — Environment spec.** `[DECISION]` v1 operates indoors on hard flat-to-moderately-irregular surfaces (≤ 30 mm obstacles for single modules; larger obstacles addressed by collective configurations). No water, dust ingress IP40, 10–35 °C. Outdoor operation is out of scope for v1.

**P0.4 — Latency and endurance budgets.** `[DECISION]` Instruction → swarm activation ≤ 10 s at 20 modules. Control tick 20 Hz. Per-sortie endurance ≥ 30 min struts, ≥ 60 min nodes (relaxed from production targets; demo sessions are short). These derive the power budget (§2.6).

**P0.5 — Activation semantics.** `[DECISION]` Two-stage commit. Stage 1 (PREPARE): goal vector `g` with version `v` diffuses by gossip; each module acks to neighbors; each module maintains a quorum estimate `q̂` (fraction of known-degree neighborhood holding version `v`, smoothed). Stage 2 (ACTIVATE): base station broadcasts an ARM signal; a module activates when it holds version `v`, `q̂ ≥ 0.8`, and ARM is present. Either condition lapsing for > 2 s causes the module to freeze in place (safe state = brakes on, magnets engaged). `[OPEN → P3.7]` Exact quorum estimator under message loss; resolved during comm-in-the-loop training.

**P0.6 — Safety specification.** Non-negotiable, enforced outside the learned policies:
1. Hardware e-stop: dedicated radio listen path checked in firmware ISR; magic packet → motor drivers disabled within 50 ms, magnets remain engaged.
2. Current/torque clamps configured in the motor driver, not in software the policy can influence.
3. Geofence: base station broadcasts a bounding box; modules estimating themselves outside freeze.
4. Watchdog: missed tick deadline > 250 ms → freeze.
5. Max collective speed 0.3 m/s in v1.

**P0.7 — Success metrics.** Per mission profile: task success rate ≥ 80 % over 20 trials at prototype scale, ≥ 70 % at production scale; zero safety-spec violations; instruction-following accuracy ≥ 90 % on the held-out instruction test set (§3.6).

**P0.8 — Interface freeze v1.** One-page interface control stubs for: NLP↔base-station, base-station↔seed-module, strut↔node message, module↔fleet-telemetry. Fleshed out in Phase 1; frozen at end of Phase 1.

### 1.3 Deliverables
Requirements document (this section instantiated with any edits), mission-profile pages, safety spec, metric definitions.

### 1.4 Exit Criteria
- [ ] All `[DECISION]` items above ratified or amended with change note
- [ ] Mission success predicates are machine-checkable (pseudocode written)
- [ ] Safety spec reviewed against every later phase's hardware/firmware plans

---

## 2. Phase 1 — Architecture Design (Weeks 4–16)

### 2.1 Objectives
Produce the full interface control document (ICD), the GNN formalization of the control system, the communication channel decision, the compute/power architecture for both module classes, and the safety architecture — all to a level where Phase 2 can simulate it and Phase 4 can build it.

### 2.2 The Swarm as a Physical Graph Neural Network (P1.1)

Let the configuration at tick *t* be graph **G_t = (N, S, C_t)** — nodes N, struts S, connections C_t ⊆ S × N × surface-position. Each strut s has hidden state h_s ∈ ℝ^32; each node n has hidden state h_n ∈ ℝ^32.

Per tick:

1. **Edge (strut) update** — strut brain computes, from its proprioception o_s (IMU, motor encoders, connector load estimates, battery), its goal vector g, its hidden state, and the last messages received from its (up to two) attached nodes:
   - `h_s ← GRU_s(h_s, [o_s, g, m_in^A, m_in^B])`
   - action `a_s = π_s(h_s)` (4 continuous values: per-connector gimbal pan/tilt velocity commands, plus 2 discrete attach/detach logits per connector). **Continuous actions are preserved under the discrete-docking prototype**: gimbal swings are fully continuous; only *attachment points* quantize, with firmware (and the sim surrogate, §3.3) snapping the commanded attach to the nearest of 26 valid positions. The policy never sees a discrete action space — the grid is an actuator nonlinearity it learns through experience, and moving to the funded-v1 freeform connector is a surrogate-file change plus fine-tuning, not an architecture change.
   - outgoing messages `m_out^A, m_out^B = f_msg(h_s)` ∈ ℝ^16 each (one per connector)
2. **Vertex (node) update** — node brain receives the set {m_out from each attached strut} (variable size, 0–12 struts per node), plus its own sensing o_n (hall-switch occupancy map over the 26 docking positions, IMU, battery):
   - aggregate with permutation-invariant pooling: `z = mean ⊕ max` over incoming messages
   - `h_n ← GRU_n(h_n, [o_n, g, z])`
   - broadcast message `m_node = f_bcast(h_n)` ∈ ℝ^16 sent to all attached struts (single broadcast, not per-strut, to bound bandwidth)

This *is* one message-passing round of a GNN with GRU updates. Properties we get for free: permutation invariance over neighbors, scale generalization across swarm sizes, and a principled meaning for the strut→node→strut signal the original concept left open — it is a learned 16-d message, trained end-to-end (Phase 3).

`[DECISION]` Hidden sizes: h = 32, messages = 16-d (int8 on the wire, dequantized on receipt). Goal vector g = 128-d float16, broadcast separately from per-tick messages (it changes rarely). Two policy classes only — all struts share weights, all nodes share weights (heterogeneous by class, homogeneous within class). Per-module identity enters through observations, not weights.

### 2.3 Message Schemas (P1.2) — wire format, frozen at phase exit

**Per-tick strut→node message (14 bytes + 16 payload = 30 B):**
`[u8 msg_type][u16 strut_id][u8 connector_id][u16 tick][u8 goal_version][u8 seq][u32 reserved/crc][i8 payload ×16]`

**Per-tick node→struts broadcast (28 B):** same header, no connector field, i8 ×16 payload.

**Goal diffusion packet (~300 B, sent on change or every 2 s):**
`[u8 msg_type][u8 goal_version][u8 hop_count][u8 q̂ ×1 (quantized)][f16 g ×128][u32 hmac-truncated]`
Modules re-broadcast on version increase; version monotonicity prevents stale-instruction loops; truncated HMAC (key provisioned at flash time) prevents trivial spoofed goals.

**Bandwidth check:** at 20 Hz, a node with 12 struts handles 12×30 B in + 28 B out per tick ≈ 7.8 kB/s ≈ 62 kbps plus overhead — comfortably inside ESP-NOW's practical ~250 kbps shared budget for a local neighborhood, with margin for goal diffusion and telemetry.

### 2.4 Physical Communication Channel — trade study and decision (P1.3)

| Option | Mechanism | Pros | Cons | Risk |
|---|---|---|---|---|
| (a) Through-connection | Modulated near-field/contact at the magnetic interface | Topology = physical truth; enables power-through-strut later | Must be invented; rolling contact makes continuous electrical contact hard; EMI from motors | High |
| (b) Local radio (ESP-NOW) + sensed topology | 2.4 GHz broadcast; physical attachment sensed directly (prototype: hall switch per docking position; funded v1: T-RO-style magnetometer array), and software filters radio traffic to physical neighbors | Off-the-shelf; decouples comms risk from connector risk; broadcast suits node→struts | Shared spectrum at scale; topology inference adds a sensing dependency | Low–Med |
| (c) Optical (IR) at connector | IR LED/photodiode pairs at interface | Immune to RF congestion | Alignment across a rolling spherical contact; ambient light | Med–High |

`[DECISION]` Ship the prototype on **(b)**: ESP-NOW for per-tick messages and goal diffusion. **Topology sensing is simplified by the discrete-docking design**: one hall-effect switch per docking position (26/node) detects occupancy directly; struts announce their ID + connector + position index over radio on latch, and the node cross-checks hall state against announcements. The T-RO-style magnetometer array and GCN localization are NOT built in the prototype — they return in funded v1 alongside the freeform connector. Software still enforces that per-tick messages are only *accepted* from physically attached neighbors. RF congestion at 20 modules is far below the original 72-module concern; keep TX power minimized and TDMA slot offsets anyway (they cost nothing and de-risk scaling demos).

### 2.5 Compute Architecture (P1.4)

`[DECISION]` Both module classes use **ESP32-S3** (dual-core LX7 @ 240 MHz, vector instructions, 8 MB PSRAM variant, native ESP-NOW). Strut adds a **DRV8833-class dual motor driver** with hardware current limit (safety spec §1.2-2). Inference runtime: **TFLite Micro / esp-nn**, int8. Policy budget per module: ≤ 100 k parameters, ≤ 5 ms inference per tick (measured headroom target ≤ 50 % core utilization). If Phase 3 distillation cannot hit 100 k params at acceptable performance, fallback `[OPEN → P3.8]` is an upgrade to a Cortex-M55+Ethos-U55 part (e.g., Alif E series) — provision the PCB with a compatible footprint decision before Phase 4 layout.

Node sensing (prototype): **26× hall-effect switches** (one per docking position, e.g., SI7201-class, ~$0.40 ea) read via GPIO expanders — replaces the 24-magnetometer array entirely for the prototype (cost −$70/node, firmware complexity −1 subsystem). Both classes: 6-axis IMU (ICM-42688), battery gauge (MAX17048).

### 2.6 Power Architecture (P1.5)

Strut budget (worst case): connector drive/latch actuation ≈ 2×1.0 W peak, ESP32-S3 ≈ 0.5 W, sensors/misc ≈ 0.2 W → design point 3.5 W peak, ~1.5 W average. 30 min endurance → ≥ 0.75 Wh usable → `[DECISION]` 1S Li-ion 18650 (2.5–3.4 Ah) per strut — oversized on purpose; cells are cheap and demo days are long. Charge via 4 exposed gold-plated pads on the strut midbody (bench charger in the prototype; racks are a v1 item).
Node budget: ESP32-S3 + 26 hall switches (µA-class) + IMU ≈ 0.7 W average → 60 min trivially met → 1S 18650 or 2.5 Ah flat LiPo if the 90 mm envelope demands it. Nodes sleep when no struts attached (wake on any hall edge — far simpler than the magnetometer wake scheme).
`[OPEN → funded v1]` Power-through-connection for nodes.

### 2.7 Structural Check for Non-Steel Active Nodes (P1.6)

The steel shell is gone, which removes the RF-cage problem (nylon is transparent; if aluminum is chosen, keep two polymer antenna windows) and most of the node mass, but introduces: insert retention (steel/magnet inserts at 26 positions must not pull out — design for ≥ 3× the connector pull force via geometry, not glue alone: through-bolted or heat-set + mechanical capture), shell stiffness under multi-strut moment loads (FDM is acceptable only for first articles; SLS nylon or machined aluminum for the fleet — pick after first-article load testing), and creep at insert seats under sustained magnetic preload. Tasks: simple FEA or hand-calc per load case; physical pull-test every insert design ×20 samples; re-derive max struts-per-node cantilever with prototype masses — feeds simulation constraints and MARL action masking.

### 2.8 NLP Front End Architecture (P1.7)

`[DECISION]` The language model never runs on the swarm. Base station (a laptop or Yoo's K3s cluster node) runs: instruction text → **frozen open-weights encoder** → projection head → g ∈ ℝ^128. Encoder choice: an open sentence-embedding model in the E5/BGE-large class (~300 M params, runs on CPU at these rates), *not* a vendor API — fine-tuning rights, offline operation, and latency determinism matter more than raw quality, and the projection head (trained in Phase 3) absorbs most of the adaptation. A vendor LLM (e.g., Claude via API) is used **offline only** for instruction-dataset generation and paraphrase augmentation (§4.6). LoRA fine-tuning of the encoder is a contingency, not the plan (§4.6 decision tree).

### 2.9 Safety Architecture (P1.8)

Implements §1.2 P0.6 concretely: e-stop listener as a dedicated FreeRTOS task at max priority polling a reserved ESP-NOW peer/magic-payload, plus a hardware line from the radio-task GPIO to the motor-driver nSLEEP pins so policy code cannot re-enable drive; brownout and stack watchdogs freeze-safe; all freeze states keep magnets engaged (passive magnets — no power needed to hold, per FreeSN's permanent-magnet connector design).

### 2.10 Deliverables & Exit Criteria
Deliverables: ICD (message schemas, timing, electrical interfaces), GNN spec with dimensions, channel trade study (above) ratified, compute/power BOM draft, structural FEA report, safety architecture document.
- [ ] ICD frozen and version-tagged
- [ ] Power budgets close with ≥ 25 % margin
- [ ] FEA shows shell penetrations keep ≥ 2× safety factor on worst-case connector loads
- [ ] Bandwidth/timing analysis closes at 20 modules (and on paper at 72 for the v1 outline)
---

## 3. Phase 2 — Simulation Environment (Months 2–6)

### 3.1 Objectives
A GPU-parallel digital twin faithful enough that policies trained in it transfer to hardware after Phase 4 calibration, with the connector surrogate model as the centerpiece.

### 3.2 Simulator Selection (P2.1)

`[DECISION]` **Isaac Lab (Isaac Sim / PhysX 5 backend)**. Rationale: native GPU-parallel rigid-body simulation at thousands of environments, USD asset pipeline, mature RL tooling, articulation supports for our joint surrogates. MuJoCo/MJX is the fallback if Isaac's contact stability with many kinematic attach/detach events proves poor (evaluate both in P2.2 spike, 2 weeks, before committing the asset pipeline). Training hardware: Yoo's local cluster for development-scale runs; cloud GPU (4–8× A100/H100 class) rented for full training runs — budget §12.

### 3.3 Connector Surrogate Model (P2.3) — the load-bearing abstraction

Do **not** simulate magnetics. The discrete-docking connector changes the kinematics from FreeSN's surface-rolling to **pivot-gait locomotion** (detach one end, swing, reattach — as in truss-robot literature). Model each strut connector ↔ node interface as:

1. **Attachment** = a dynamically created joint locking the connector base to one of the node's 26 docking positions, with a **2-DOF actuated gimbal** (pan/tilt) between connector base and strut body — the gimbal is how a latched strut swings its free end. Gimbal driven in velocity mode with datasheet torque/velocity limits.
2. **Holding model**: joint breaks when constraint force exceeds `F_pull(α)` or moment exceeds `M_break(α)` (α = load angle from docking-position normal). Initialize F_pull(0) = 35 N (smaller connector, lighter modules); **placeholder, replaced by P4.7 bench data.**
3. **Attach event**: when an open connector is within 10 mm and 20° of *any* docking position and the attach logit fires, snap to that position and create the joint after a 150 ms latch latency (placeholder). The snap IS the quantization layer — policies command continuous targets, attachment lands on the grid.
4. **Transit between positions on the same node** = detach → swing (gimbal of the still-attached far connector) → reattach. There is no surface rolling in the prototype.
5. **Latch reliability**: per-attach success probability term (randomized, §3.5) so policies learn retry behavior.

`[DECISION]` Surrogate parameters live in one YAML (`connector_surrogate.yaml`) with provenance comments; Phase 4 calibration PRs edit only this file. This file *is* the sim2real contract.

### 3.4 Module Assets & Sensor Models (P2.4)

USD assets from Phase 1 CAD (masses/inertias exported, not guessed). Sensor models: IMU with bias+noise, gimbal angle feedback with backlash, hall-occupancy map abstracted as "per-position attached-strut-id with detection latency and a small miss probability" — we simulate the *output* of the sensing, not the magnetics. Communication simulated as the actual message schema (§2.3) with configurable per-link drop rate, latency jitter, and tick desynchronization (modules tick at 20 Hz ± drift).

### 3.5 Domain Randomization Plan (P2.5)

| Parameter | Range (initial) | Note |
|---|---|---|
| F_pull scale | ×[0.6, 1.3] | per-connector, per-episode |
| Surface friction | [0.4, 1.1] | per-episode |
| Latch success prob | [0.85, 1.0] | per-attach |
| Gimbal backlash | [0, 3]° | per-joint |
| Motor torque scale | ×[0.8, 1.1] | per-module |
| Actuation latency | [10, 60] ms | per-module |
| Message drop | [0, 15] % | per-link |
| Tick desync | [0, 25] ms | per-module |
| Mass/inertia | ×[0.95, 1.1] | per-module |
| IMU bias walk | per datasheet ×[1, 3] | |
| Attach latch latency | [100, 300] ms | |

Ranges narrowed/centred by P4.7 measurements; drop-rate range *widened* if hardware RF testing (P4.8) shows worse.

### 3.6 Scenario Suite (P2.6)

Implement the four P0.1 mission profiles plus micro-scenarios used by the curriculum (§4.4): single-strut pivot step (swing free end to a commanded docking position), strut walk between two nodes, triangle formation, tetrahedron formation, connected-gait locomotion of a 6-module truss, gap crossing (gap = 1.5× strut length), payload drag (payload = 2× module mass), shape-command assembly (target adjacency matrix given via g). Every scenario has: reset distribution, success predicate (from P0.1), time limit, and a scripted-baseline score (hand-coded heuristic) to sanity-check learnability.

### 3.7 Repo & Infrastructure (P2.7)

Monorepo: `/sim` (Isaac Lab tasks), `/policies` (training, §4), `/firmware` (Phase 4), `/basestation` (NLP + fleet tools), `/hw` (CAD/PCB), `/docs`. CI runs scenario smoke tests on every PR (CPU, 1 env, 200 steps). Experiment tracking: Weights & Biases or MLflow; every training run logs the surrogate YAML hash — runs are not comparable across surrogate versions otherwise.

### 3.8 Deliverables & Exit Criteria
- [ ] 2-week simulator spike report (Isaac vs MJX) and ratified choice
- [ ] All 4 mission scenarios + 8 micro-scenarios runnable at ≥ 512 parallel envs on the local RTX 4060 with > 8k env-steps/s aggregate (and verified to scale to ≥ 4,096 envs on an A100 spot instance in one ≤ $10 smoke test)
- [ ] Attach/detach events stable (no constraint explosions) over 1 M random-action steps
- [ ] Scripted baselines achieve non-zero success on micro-scenarios (proves predicates and physics are sane)
- [ ] Surrogate YAML + sensor/comm models documented

---

## 4. Phase 3 — MARL + NLP Training (Months 4–12)

### 4.1 Objectives
Train the two policy classes end-to-end with learned communication, conditioned on language-derived goal vectors; distill to MCU-deployable networks.

### 4.2 Algorithm (P3.1)

`[DECISION]` **MAPPO under CTDE.** Two actor classes (strut, node — architectures per §2.2) with parameters shared within class. One centralized critic per task: a GNN critic over the full configuration graph (privileged state: true poses, true topology, task state). Communication messages are continuous and differentiable during training (gradients flow through the physically-routed message graph); int8 quantization of messages is introduced in late training as quantization-aware noise so deployment matches.

Key hyperparameters (starting point, tuned thereafter): lr 3e-4 cosine-decayed, γ 0.99, GAE λ 0.95, PPO clip 0.2, entropy coef 0.01 annealed, 512–1,024 envs × 64-step rollouts (local 4060), minibatch 8k transitions, 4 epochs/update. Action space per strut: 4 continuous (wheel velocity pairs) + 2×2 discrete attach/detach (masked by feasibility — e.g., cannot detach if it would exceed the cantilever limit from P1.6 or disconnect the graph when connectivity is required by the task). Node "action" is purely its broadcast message (nodes don't move themselves).

### 4.3 Reward Design (P3.2)

Per scenario: sparse terminal success reward (+10) plus annealed dense shaping. Standard shaping library: potential-based distance-to-goal terms, connectivity-maintenance bonus, energy penalty (∝ Σ|torque·ω|), message-entropy regularizer early (encourages informative comms), attach/detach action cost (discourages chattering), safety penalties mirroring P0.6 (overspeed, geofence) so the policy *also* learns the limits the firmware enforces. All shaping coefficients in per-scenario YAML; anneal dense terms to ≤ 10 % of return by curriculum stage end.

### 4.4 Curriculum (P3.3) — stages with promotion criteria

| Stage | Setup | Promote when |
|---|---|---|
| C1 | 1 strut, 1 node: pivot free end to commanded docking position | ≥ 95 % success |
| C2 | 1 strut, 2 nodes: pivot/walk between nodes | ≥ 90 % |
| C3 | 3 struts, 3 nodes: form commanded triangle | ≥ 90 % |
| C4 | 4–6 modules: tetrahedron; connected-gait locomotion to waypoint | ≥ 85 % |
| C5 | 6–12 modules: reconfiguration A→B given target adjacency in g | ≥ 80 % |
| C6 | Full mission profiles (a)–(d), goal-conditioned, randomized scale 6–20 modules | ≥ 80 % |
| C7 | **DEFERRED TO FUNDED v1.** Scale generalization beyond 20 modules is a funded-v1 task; do not spend compute on it | — |

Comm constraints (drop, latency, desync from §3.5) are present from **C3 onward** — never train clean-comm policies you must later break. Goal vector g is a fixed task one-hot+parameters embedding through C5; real language embeddings enter at C6 (below).

### 4.5 Quorum/Activation Learning (P3.4, closes `[OPEN]` P0.5)

The gossip/quorum layer is **engineered, not learned**: implemented exactly per §2.3 goal-diffusion packets inside the simulated comm stack, with the quorum estimator = exponential smoothing of neighbor-ack fraction with degree-weighted correction. Validated under §3.5 drop rates at 20 modules (and 64 in sim only, zero cost, for the pitch deck); tune θ and smoothing only. Policies are trained *with* the activation machinery active so frozen/pre-activation behavior is in-distribution.

### 4.6 NLP Pipeline (P3.5–3.6)

1. **Instruction dataset**: define a task grammar covering the mission space (task type, shape target, location/direction, payload reference, constraints). Author ~150 seed instructions/task manually; expand to ~8–10k via LLM paraphrase generation (vendor API, offline); every generated item is auto-checked by parsing back to grammar slots and 10 % human-audited. Split 80/10/10 with paraphrase-disjoint test set.
2. **Projection head**: 2-layer MLP, encoder-embedding → 128-d g, trained jointly with C6 RL **and** with an auxiliary supervised loss (g must linearly decode back to grammar slots — keeps g grounded and gives a fast offline eval).
3. **Decision tree for encoder fine-tuning**: if instruction-following accuracy on the held-out set ≥ 90 % with frozen encoder → done. If 75–90 % → LoRA-tune encoder on the supervised (instruction → slots) objective only, re-evaluate. If < 75 % → revisit grammar/dataset before touching the encoder (the bottleneck is almost certainly data, not the encoder).

### 4.7 Distillation & Quantization (P3.7)

Teacher policies (32-d hidden, fp32) → students sized for the MCU: DAgger-style distillation in sim (student acts, teacher labels), int8 quantization-aware training, message vectors quantized to match wire format. Acceptance: student ≤ 100 k params/class, ≤ 5 ms on ESP32-S3 (measured on devkit, not estimated — this is the P3↔P4 handshake), task success within 5 % absolute of teacher across C6 suite. If infeasible → trigger the P1.4 MCU fallback *before* Phase 4 PCB layout freezes.

### 4.8 Training Compute & Run Plan (P3.8)

`[DECISION]` **Local-first on the RTX 4060 (8 GB) in Yoo's K3s cluster.** Sizing: 512–1,024 parallel envs (VRAM-bound, not compute-bound) → expect 1–2 weeks wall-clock per full C1–C6 run at prototype scale. All curriculum development, ablations, and at least the first 2 full runs are local. Cloud is a safety valve only: single A100-class **spot** instance (Vast.ai/Lambda, ~$1–2/hr), per-run projected cost ≤ $50 without approval, **cumulative cloud cap $400 (guardrail §0.0-3)**. Seeds: 2 per milestone stage locally (3 if schedule allows); report median. Checkpoint every 30 min — spot instances and home power are both interruptible.

### 4.9 Deliverables & Exit Criteria
- [ ] C6 promotion criteria met (2 seeds, median)
- [ ] 64-module sim evaluation run once for the pitch (no training, no cloud spend)
- [ ] Instruction test-set accuracy ≥ 90 %
- [ ] Distilled int8 students meet §4.7 acceptance on real devkit hardware
- [ ] Full training reproducible from repo + configs (one-command relaunch)
---

## 5. Phase 4 — Hardware Prototyping (Months 6–14, overlaps Phase 3)

### 5.1 Objectives
Build and bring up the 20-module fleet (12 struts + 8 nodes) in two waves — first articles (2+2) then the fleet (10+6) only after first articles pass — producing the calibration data that retunes the simulation surrogate (§3.3) along the way.

### 5.2 Mechanical Work Breakdown

**P4.1 — Connector (the crown jewel; do this first).** Prototype connector = **discrete magnetic dock + actuated gimbal + mechanical release**:
- *Dock*: N52 magnet in the connector face mating to a steel insert (or opposing magnet) at each of the node's 26 positions; target F_pull(0) ≈ 35 N — bench-iterate magnet size against insert geometry.
- *Release*: a small servo/cam lever that peels or tilts the magnet to break the circuit (never fight full pull force directly). This is the highest-iteration-risk part; build it standalone on day one with printed parts before any strut exists.
- *Gimbal*: 2-DOF pan/tilt between connector base and strut body, two micro gearmotors or smart servos (torque sized to swing a 350 g strut cantilevered at 220 mm with 2× margin → roughly ≥ 0.8 N·m at the joint; verify with the actual mass spreadsheet).
- *Alignment*: chamfered self-centering geometry at the dock so the ±10 mm/±20° capture envelope (§3.3-3) is mechanically real.
Freeform rolling connectors (FreeSN-faithful) are explicitly NOT built now; they are funded-v1 work, and the papers remain the reference for that upgrade.
**P4.2 — Strut body.** Tube chassis (aluminum or even CF arrow-shaft stock) housing battery, PCB, wiring to both connector gimbals; charge pads on midbody; mass budget ≤ 350 g enforced (running spreadsheet, weighed at every build).
**P4.3 — Node.** Two-hemisphere **SLS nylon** shell (service bureau, e.g., JLC3DP/Craftcloud; FDM acceptable for first articles only) or machined aluminum if load testing demands it; 26 docking positions each carrying a captured steel insert (through-bolted or mechanically trapped per §2.7) and a hall-effect switch on the inner surface; internal carrier holding PCB, battery, charge pads. No antenna window needed for nylon; two polymer windows if aluminum is chosen. Pull-test every insert design ×20 before fleet build.

### 5.3 Electronics (P4.4)

`[DECISION]` **Revision A is devkit-based, not custom**: ESP32-S3 devkit + breakout motor drivers (DRV8833 with hardware current limit) + hand-wired harness inside the strut tube. Ugly, but it eliminates one custom-PCB cycle (~$600–800 saved) and lets firmware development start in week 1. **Revision B** (one custom board per class, JLCPCB/PCBWay econo assembly) is built only after Rev-A modules pass C1–C2-equivalent hardware tests. Strut board: ESP32-S3-WROOM, DRV8833 ×2, encoder/servo inputs, IMU, fuel gauge, pad-charging with ideal-diode, UART/JTAG header. Node board: ESP32-S3, hall-switch matrix via GPIO expanders, IMU, gauge, charging. Pre-layout: confirm the §4.7 MCU decision (distillation feasibility on devkit) — the board carries the consequence.

### 5.4 Firmware (P4.5)

FreeRTOS on ESP-IDF. Task set: (1) safety/e-stop (highest prio, owns nSLEEP line), (2) 20 Hz tick scheduler (comm RX window → inference → actuation → TX window, with TDMA slot offset by module ID), (3) ESP-NOW stack + message schema codecs, (4) goal-diffusion/quorum module (engineered per §4.5), (5) TFLite Micro inference, (6) sensing drivers (IMU, encoders/servo feedback; node: hall-switch matrix scan with debounce + attach/detach event generation), (7) telemetry/OTA (esp_https_ota against base station; signed images). Watchdogs per P0.6.

### 5.5 Bring-up Checklist (P4.6)

Per board: power rails → flash → radio range test → sensor sanity → motor spin → current-limit verification (force a stall; confirm clamp) → e-stop latency measurement (must be ≤ 50 ms) → inference timing on-target. Per module: weighed, balanced, connector pull-force tested. Per pair: attach/detach cycle test ×500 across multiple docking positions, logging latch latency, success rate, and any misses.

### 5.6 Calibration Experiments → Simulation (P4.7) — the sim2real contract

Bench rigs + scripted firmware modes measure, with N ≥ 10 samples each:
- F_pull(α) and M_break(α) at α ∈ {0°, 15°, 30°, 45°, 60°} per docking insert → replaces surrogate lookup table
- Attach latch latency + success-rate distribution; capture envelope (offset/angle at which self-centering dock succeeds) → calibrates §3.3-3/-5
- Gimbal torque/velocity as-built; backlash measurement
- Actuation latency (command → motion onset), motor torque constants as-built
- Hall-switch detection reliability per position ×100 cycles
- Battery endurance under scripted duty cycles (validates §2.6 budgets)
- RF: packet-loss vs distance/orientation at 20 modules (P4.8) → updates §3.5 drop ranges
Each experiment outputs a PR editing `connector_surrogate.yaml` / DR ranges with data attached. **Phase 3's final training runs use post-calibration values** — schedule the calibration before the budgeted full training runs (§4.8), i.e., target calibration complete by month ~10.

### 5.7 Through-Connection Investigation (P4.10) — funded-v1 item, DO NOT EXECUTE NOW

Retained as a funded-v1 backlog item (bench study of contact-ring or near-field power/data through the connector). Zero prototype budget is allocated to it; agents must not start it (guardrail §0.0-5).

### 5.8 Deliverables & Exit Criteria
- [ ] First articles (2 struts + 2 nodes) pass, then full 12+8 fleet built, bring-up checklist green on every module
- [ ] 500-cycle attach/detach with ≥ 99 % latch success
- [ ] Calibration dataset merged; surrogate YAML updated; sim re-validated (scripted baselines still pass)
- [ ] E-stop ≤ 50 ms verified on every module
- [ ] OTA + telemetry functional end to end

---

## 6. Phase 5 — Sim2real Transfer (Months 12–18)

### 6.1 Protocol (P5.1–P5.4)

1. **Replay validation**: drive hardware with scripted action sequences from sim rollouts (C1–C3 scale); compare trajectories (pose error, attach success) — quantifies residual sim gap before any policy runs.
2. **Staged policy deployment**: distilled students on hardware in curriculum order C1 → C6, scaling hardware 4 modules → 12 → 20. Promotion mirrors §4.4 but with hardware success thresholds 10 points lower initially.
3. **Gap closure loop**: failures triage to (a) surrogate parameter error → recalibrate (P4.7 rig), retrain affected stages; (b) unmodeled effect (cable snag, EMI, slip regime) → add to sim + DR, retrain; (c) policy brittleness → widen DR, retrain. **Online RL on hardware is prohibited in v1** (safety + sample cost); the permitted on-hardware learning is **offline**: log everything (P5.3 fleet logging), and if needed run offline fine-tuning (IQL/AWAC-style) on logged data with sim-evaluation gating before redeploy.
4. **Instruction-in-the-loop dry runs**: full pipeline — typed instruction → encoder → g → seed injection → diffusion → quorum → ARM → execution — at 20 modules, 20 scripted instructions, measuring end-to-end latency against the 10 s budget. **This demo, on video, is the centerpiece of the funding pitch.**

### 6.2 Fleet Tooling (P5.3)

Base station services (containerized on Yoo's K3s cluster): telemetry ingest (per-tick downsampled + event logs from every module), Grafana dashboard (per-module health, swarm topology live view from node localization), OTA orchestrator with staged rollout + rollback, log lake for offline RL, regression harness that replays the 20-instruction suite and diffs success/latency after any firmware or policy change.

### 6.3 Exit Criteria
- [ ] C4-equivalent behaviors ≥ 75 % and at least one full mission profile ≥ 60 % success on the 20-module hardware swarm
- [ ] End-to-end instruction latency ≤ 10 s
- [ ] Zero safety violations across all hardware testing
- [ ] Gap-closure loop demonstrated at least twice (documented failure → sim fix → retrain → hardware pass)

---

## 6P. Phase 6P — Demo Hardening & Funding Package (Months 12–15)

### 6P.1 Objectives
Convert a working 20-module swarm into something fundable. This phase IS in scope.

### 6P.2 Work Breakdown
**P6P.1 — Reliability hardening.** The demo must run 10 times in a row without intervention: fix the top failure modes from Phase 5 logs (latch misses, comms dropouts, battery surprises) until the 20-instruction regression suite passes ≥ 9/10 full sessions.
**P6P.2 — Demo script.** Three live demos, 5 minutes each, ordered by reliability: (1) instruction-conditioned self-assembly into two different commanded shapes, (2) connected-gait locomotion to a waypoint, (3) cooperative transport. Each has a rehearsed narration and a pre-recorded backup video.
**P6P.3 — Pitch materials.** Deck covering: the working demo, the GNN-as-physical-swarm framing (this is the differentiator — the intelligence stack, not the mechanism), the sim2real pipeline as repeatable infrastructure, and the funded-v1 roadmap (freeform connectors, magnetometer localization, 72+ modules, through-connection power — i.e., §7–8 below). Include the honest limitations slide: discrete docking, indoor-only, pivot gait speed.
**P6P.4 — Documentation freeze.** Tag the repo, archive the spend ledger (proof of capital efficiency — building this for <$10k is itself a pitch point), record the bench data.

### 6P.3 Exit Criteria
- [ ] 9/10 unattended regression sessions pass
- [ ] Three demos rehearsed live ≥ 3× each + backup videos recorded
- [ ] Deck + technical appendix complete
- [ ] Spend ledger final, total ≤ $10k

---

# ============================================================
# POST-FUNDING OUTLINE — §7 AND §8 ARE OUT OF SCOPE FOR EXECUTION
# Retained to show investors the path. Guardrail §0.0-5 applies:
# no agent may begin, purchase for, or contract for anything below
# until funding closes and a human change note re-activates them.
# ============================================================

## 7. Phase 6 — Production Manufacturing (post-funding; originally Months 15–24)

### 7.1 DFM Pass (P6.1)
Re-design prototype for quantity ~100 modules (72 + spares): replace machined strut parts with extrusion + molded end housings where tolerance allows; nodes remain spun/stamped steel hemispheres (get DFM feedback from the vendor early — shell sphericity tolerance directly affects connector rolling, spec it from P4.7 data); panelized PCBs; wiring → board-to-board connectors; assembly work instructions written and photographed from a pilot build.

### 7.2 Vendor Strategy (P6.2)
PCBA: JLCPCB/PCBWay (proto) → re-quote at volume incl. US options (e.g., MacroFab) for the production lot. Mechanical: Xometry/Protolabs for bridge quantities; dedicated metal spinner for shells; **magnets dual-sourced** (long lead, quality variance — incoming pull-force test 100 %). Batteries: reputable 18650 distributor with traceable cells. Every long-lead item gets a second source identified even if unused.

### 7.3 Quality & Acceptance (P6.3)
Incoming: shell pull-force + sphericity, magnet array force, cell capacity sample test. End-of-line per module: full bring-up checklist (§5.5) automated into a test fixture (pogo-pin bed for boards; attach/detach robot fixture cycling each connector ×50), firmware flashed + provisioned (identity, HMAC key), results logged to fleet DB. Yield tracking; FA on every failure.

### 7.4 Regulatory & Logistics (P6.4)
FCC Part 15 / CE RED for the 2.4 GHz radio — using a pre-certified ESP32-S3 module keeps this to unintentional-radiator testing (budget one EMC lab pass + one re-spin contingency); UN38.3 + proper packaging for any air shipment of cells; basic product-safety review (pinch points at connectors, magnet ingestion warnings).

### 7.5 Exit Criteria
- [ ] Pilot lot (20 modules) ≥ 90 % first-pass yield; issues dispositioned
- [ ] Production lot delivered: 48 struts + 24 nodes + 10 % spares
- [ ] 100 % end-of-line records in fleet DB
- [ ] EMC test report passed

---

## 8. Phase 7 — Swarm Integration, Scaling, Operations (post-funding; originally Months 18–30)

### 8.1 Staged Scale-up (P7.1)
Hardware stages: 10 modules → 30 → 72. **Before each stage**: sim evaluation at exactly that scale and the C7 check; RF congestion measurement at the new density (P4.8 rig method) with channel-plan adjustment if loss exceeds the trained DR range. At each stage run the regression instruction suite + one new mission profile.

### 8.2 Full Mission Validation (P7.2)
The four P0.1 missions at production scale against P0.7 metrics (≥ 70 %, 20 trials each). Failures feed the Phase 5 gap-closure loop (which remains a standing process, not a finished phase).

### 8.3 Charging Infrastructure (P7.3)
`[DECISION]` v1 charging is a **rack**, not autonomous docking: shelving with sprung contact rails matching strut midbody pads and node window pads; humans rack modules; rack reports per-slot charge state to the fleet DB. Autonomous return-to-charge is a v2 behavior (it is "just" another mission profile once the rack has a beacon — note for the v2 backlog).

### 8.4 Maintenance & Operations (P7.4)
Spares pool ≥ 10 %; wheel/pad wear inspection interval from the 500-cycle data; battery health from fleet gauge telemetry with retirement threshold (≤ 80 % capacity); quarterly full-fleet regression after any policy/firmware release; incident log with mandatory FA for any safety-adjacent event.

### 8.5 Exit Criteria (program v1 complete)
- [ ] 72-module swarm executes all four missions at P0.7 thresholds
- [ ] 30 days of operations with zero safety violations
- [ ] Ops runbook written; a person other than the builders can run a session from it
---

## 9. Risk Register

| # | Risk | Likelihood | Impact | Mitigation | Trigger/Fallback |
|---|---|---|---|---|---|
| R1 | Magnetic dock + release mechanism unreliable (latch misses, peel servo wear) | Med | Critical (gates everything physical) | P4.1 built standalone in week 1; self-centering geometry; 500-cycle test gate before fleet build | If 6 weeks without ≥95 % latch reliability: enlarge capture chamfer, reduce positions 26→12, or add mechanical hook backup |
| R2 | Sim surrogate misses a dominant physical effect | Med–High | High | Calibration loop is a scheduled deliverable, not best-effort; replay validation (P5.1) before policy deployment | Repeated transfer failure → add MJX cross-check sim; expand DR |
| R3 | MARL fails to reach C5/C6 quality | Med | High | GNN structure, curriculum, scripted baselines proving learnability; 30 % compute contingency | Fall back to hierarchical control: learned low-level skills + scripted/planned reconfiguration sequencer |
| R4 | Distilled policy won't fit/meet timing on ESP32-S3 | Med | Med | §4.7 acceptance tested on devkit before Rev-B PCB freeze | Pre-planned MCU upgrade path (P1.4) |
| R5 | 4060 (8 GB) too slow/small for C5–C6 convergence | Med | Med | 512–1,024 env sizing; checkpointing; ablations at reduced scale first | Cloud spot within the $400 cap (§0.0-3); shrink hidden sizes 32→24 |
| R6 | Printed node shell/inserts fail under multi-strut loads | Med | Med | P1.6 insert pull-tests ×20; first-article load test before fleet | Switch shell to machined aluminum (~+$60/node, still in budget margin) |
| R7 | Instruction grounding poor on novel phrasings | Med | Med | Grammar-anchored dataset, paraphrase-disjoint test, decode auxiliary loss | LoRA per §4.6 tree; constrain UI to template-assisted input |
| R8 | Budget overrun past $10k | Med | High | Guardrails §0.0-1/-2; spend ledger; devkit-first Rev A; first-article gate before fleet parts order | Drop fleet from 12+8 to 8+6 (still demos all behaviors); pause and fundraise on partial demo |
| R9 | Agent-swarm scope drift (building the wrong thing or overspending) | Med | High | Guardrails §0.0 binding; spend ledger reviewed by human weekly; [DECISION] freeze; change-note process | Any violation: halt agent execution, human audit, resume only after change note |
| R10 | Safety incident during hardware testing | Low | Critical | P0.6 enforced in hardware; e-stop verified per module; speed caps; no online RL | Any incident: full stop, FA, change note before resumption |

## 10. Program-Level Dependencies (critical path)

P4.1 dock/release mechanism → first articles (2+2) → P4.7 calibration → final Phase 3 training runs → distillation acceptance → Phase 5 transfer at 20 modules → Phase 6P funding package. The dock/release mechanism is the critical path origin; it is built standalone in week 1. Phase 3's early curriculum (C1–C4 with placeholder surrogate values) deliberately runs in parallel and is treated as disposable pre-training. **The fleet parts order (10+6) is the single largest spend event and is gated on first-article success — this gate is the program's main financial protection.**

## 11. Team & Execution Model

| Role | Who | Owns |
|---|---|---|
| Human principal | Yoo | Change notes, all approvals per §0.0, weekly spend-ledger review, demo decisions |
| Agent workstreams | Agent swarm | Execution within guardrails: sim (§3), training (§4), firmware (§5.4), docs/analysis |
| Human-only tasks | Yoo (+ help as available) | Physical builds, bench rigs, soldering, hardware tests, vendor ordering ≥ $250, anything requiring hands |

Agents cannot perform physical work; every hardware task in Phase 4–5 bottoms out in human hands. Schedule assumes ~10–15 human hours/week on hardware once Phase 4 starts.

## 12. Budget Envelope (rough order of magnitude, USD)

**HARD CAP: $10,000 (guardrail §0.0-1). Spend ledger at `/docs/spend_ledger.md` is the source of truth.**

| Item | Budget | Notes |
|---|---|---|
| Connector dev (magnets, servos, printed iterations ×3) | $700 | Week-1 standalone build; highest iteration risk |
| First articles: 2 struts + 2 nodes (devkit Rev A) | $900 | Gates everything below |
| Rev-B custom PCBs (strut + node, fab + econo assembly) | $1,100 | Only after Rev-A passes C1–C2 hardware |
| Fleet electronics (ESP32-S3, drivers, sensors, halls ×fleet) | $1,300 | Ordered only after first-article gate |
| Fleet mechanical (SLS shells, tubes, inserts, gimbals, motors) | $2,200 | Largest single category; quotes before order |
| Batteries + protection + bench charger | $450 | |
| Bench rigs (pull-force, cycle tester, jigs) | $500 | Mostly printed + a luggage scale + cheap load cell |
| Cloud training (spot only) | $400 | Cap per §0.0-3; $0 is the goal (local 4060) |
| Tools/consumables (wire, fasteners, solder, shipping) | $700 | |
| Contingency (unallocated; human-approval only to release) | $1,750 | ~17.5 % |
| **Total** | **$10,000** | |

Deferred to funded v1 (do not spend now): freeform connectors, magnetometer arrays, EMC testing, charging racks, production tooling, any module beyond 20.

## 13. Change Notes

*(Append dated entries here. Each note: what changed, why, which `[DECISION]`/exit criteria are affected. Only the human principal may approve entries.)*

**CN-001 — 2026-06-11 — v1.0 → v2.0 Prototype-First Revision (approved: Yoo).**
Scope rebaselined from a $245–490k production program to a ≤$10k, 20-module funding prototype. Changes: (a) added binding agent-execution guardrails (§0.0); (b) P0.2 scale → 12 struts + 8 nodes, 220 mm/90 mm envelope; (c) connector redesigned from FreeSN freeform rolling to 26-position discrete magnetic dock + 2-DOF gimbal, pivot-gait kinematics — policy action space remains continuous, attachment quantized by firmware/surrogate snap (§2.2, §3.3, §5.2); (d) node shells → SLS nylon/aluminum with captured steel inserts; magnetometer array replaced by per-position hall switches; (e) training → local-first on RTX 4060, cloud spot capped at $400; C7 scale-generalization deferred; (f) electronics Rev A devkit-based; (g) Phases 6–7 fenced as post-funding outline; new Phase 6P (demo hardening + funding package) added; (h) budget §12 rewritten to the $10k cap with first-article gating. Rationale: available capital is $10k; the funding milestone is a reliable 20-module instruction-conditioned demo, and the intelligence stack (GNN policies, MARL pipeline, NLP front end) is preserved unchanged so funded v1 reuses it directly.

---

## Appendix A — Frozen Parameter Defaults (initial values; provenance per section)

| Parameter | Value | Set in |
|---|---|---|
| Swarm size (prototype) | 12 struts / 8 nodes (20 total) | P0.2 |
| Strut length / node Ø | 220 mm / 90 mm | P0.2 |
| Docking positions per node | 26 (truncated-icosahedron grid) | §0.1 / §5.2 |
| Module mass caps | strut ≤ 350 g / node ≤ 350 g | P0.2 |
| Tick rate | 20 Hz | P0.4 |
| Goal vector | 128-d f16 | §2.2 |
| Message vector | 16-d i8 | §2.2 |
| Hidden state | 32-d | §2.2 |
| Quorum θ | 0.8 | P0.5 |
| F_pull(0°) placeholder | 35 N | §3.3 (replaced by P4.7) |
| Policy budget | ≤100 k params, ≤5 ms on ESP32-S3 | §2.5 |
| E-stop latency | ≤50 ms | P0.6 |
| Endurance | 30 min strut / 60 min node | P0.4 |
| Max collective speed | 0.3 m/s | P0.6 |
| Budget hard cap | $10,000 | §0.0-1 |
| Cloud cap | $400 cumulative / $50 per run | §0.0-3 |
| Single-purchase approval threshold | $250 | §0.0-2 |

## Appendix B — Instruction Grammar Sketch (basis for §4.6 dataset)

`<instruction> ::= <task> [<target>] [<location>] [<constraint>]*`
- task ∈ {assemble, traverse, transport, manipulate, disperse, hold, return}
- target: shape spec (named: line|triangle|tetra|truss-NxM | adjacency hash) or object reference
- location: direction+distance | zone id | beacon id
- constraint: speed cap | keep-connected | avoid zone | module-count limit

Every dataset instruction must parse to this grammar; the auxiliary decode loss (§4.6-2) reconstructs these slots from g.

## Appendix C — Reference Anchors

- Tu, Liang, Lam. *FreeSN: A Freeform Strut-node Structured Modular Self-reconfigurable Robot — Design and Implementation.* ICRA 2022. (Connector mechanics, module specs, four demo tasks.)
- Tu et al. *Configuration Identification for a Freeform Modular Self-Reconfigurable Robot — FreeSN.* IEEE T-RO 2023. (Node magnetometer array, GCN-based connector localization — basis for funded-v1 node sensing; prototype uses hall switches instead.)
- MAPPO: Yu et al. 2021. GNN/learned-communication MARL: CommNet, TarMAC lines of work. Offline RL for §6.1: IQL (Kostrikov et al.).
