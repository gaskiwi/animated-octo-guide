# BENCH_PROTOCOL.md — P4.1 Week-1 Connector Dev-Kit Bench Tests

> **All procedures are DRAFT. Results feed `connector_surrogate.yaml` via a calibration PR (plan §5.6). Any safety concern (e.g., magnet pinch) → stop and flag to Yoo.**

---

## Procedure A: Latch-Release Hand Test

**Goal:** Verify the release lever mechanically breaks the magnetic connection without fighting full pull force (i.e., the lever geometry provides mechanical advantage sufficient to peel the magnet rather than overcome it head-on).

**Equipment:** Assembled connector prototype, bench PSU (5 V / 2 A), or direct servo drive via servo tester; rigid table clamp or vise.

1. **Fixture setup.** Clamp the node-side steel insert (or a 10 mm dia. × 3 mm thick mild-steel disc on a flat steel plate) securely to a vise or bench clamp so it cannot move. Mount the connector assembly with its release-lever mechanism free to actuate. Confirm the servo is unpowered and the lever is in the latched (closed) position.

2. **Manual latch.** Press the connector face to the steel insert until the magnet seats fully — you will feel/hear it snap. Confirm it is held without any external force.

3. **Actuate the release lever.** Power the servo via bench PSU or servo tester (4.8–6 V). Command the servo to the release angle (defined in firmware as `RELEASE_DEG`). If no servo is yet installed, push the lever arm to the release stop by hand using a pencil eraser tip — do not use fingers near the magnet gap.

4. **Observe and record.** Note: (a) whether the connector releases (magnet separates from insert), (b) whether the servo makes any stall noise or the lever binds, (c) approximate peel angle (estimated from lever geometry). Record qualitative result: CLEAN / BIND / NO-RELEASE.

5. **Repeat.** Re-latch and repeat steps 2–4 a total of 10 times. Record each result in the table below.

6. **Pass/fail.** **PASS:** 10/10 clean releases with no servo stall sound, no binding, no manual assist needed. **FAIL:** any stall, bind, or no-release event → log the failure geometry and escalate to connector design review before ordering fabricated parts.

| Run | Result (CLEAN / BIND / NO-RELEASE) | Notes |
|----:|------------------------------------|-------|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |
| 8 | | |
| 9 | | |
| 10 | | |

**Overall: PASS / FAIL** (circle one) — Date: _______ — Tester: _______

---

## Procedure B: F_pull(0°) Luggage-Scale Measurement

**Goal:** Measure the zero-angle axial pull force for the 10 mm × 3 mm N52 magnet against a steel insert, to validate (or replace) the 35 N placeholder in `connector_surrogate.yaml`.

**Equipment:** Digital luggage scale with peak-hold (0–50 kg, 0.1 kg resolution), bench vise or C-clamp, mild-steel disc or plate (≥ 3 mm thick), hook or small plate bonded/screwed to the magnet carrier.

> **Safety:** N52 magnets at 10 mm snap together with surprising force and can pinch skin. Keep fingers clear of the gap. Use the lever or a non-ferrous rod to control seating.

1. **Fixture.** Clamp the steel insert (or a 10 mm dia., ≥ 3 mm thick mild-steel disc seated in a non-ferrous bracket) rigidly to a vise bolted to the bench. Attach the luggage-scale hook to the magnet carrier such that the pull direction will be exactly perpendicular (normal) to the magnet face (0° — straight axial pull).

2. **Seat the magnet.** Using the release lever or a non-ferrous rod to control the approach, lower the magnet carrier onto the steel insert until fully seated (face-to-face, flush in the dock recess geometry if available; otherwise flat face-to-face on the steel disc). Confirm zero lateral offset.

3. **Pull and read.** With the scale in peak-hold mode, pull slowly and steadily in the normal (axial) direction. Rate: approximately 1 cm/s — fast pulls underread due to dynamic effects. Read and record the **peak value** displayed on the scale.

4. **Convert units.** If the scale reads in kgf, convert: N = kgf × 9.81. Record both. Example: 3.6 kgf = 35.3 N.

5. **Repeat ×5.** Re-seat the magnet and repeat steps 2–4 five times. Record all peak values.

6. **Pass/fail.** Calculate mean and minimum from the 5 runs. **PASS:** mean ≥ 25 N (the bench fixture underestimates full-insert force because it lacks the recessed pocket geometry; flag for recalibration once the SLS node insert is fabricated). **FAIL (force too low):** mean < 25 N → check for off-axis seating or non-ferrous contamination; flag for magnet spec review. Update `connector_surrogate.yaml → F_pull_0deg_N` with the measured mean.

| Run | Peak (kgf) | Peak (N) |
|----:|----------:|--------:|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| **Mean** | | |
| **Min** | | |

**Overall: PASS / FAIL** — Date: _______ — Tester: _______

---

## Procedure C: CN-002 IR Line-of-Sight + Worst-Case Sunlight Pass/Fail

**Goal:** Verify the UART-over-IR link (CN-002 Layer 1) works inside the dock recess geometry AND survives direct sunlit-room ambient light — the primary failure mode for non-shrouded IR, per CN-002 risk R1b.

**Equipment:** ESP32 dev board (or function generator for 38 kHz carrier), TSAL6400 emitter, TSOP38238 demodulator, dock recess mockup (printed PLA from `dock.scad` or cardboard proxy with identical shroud depth ≥ 8 mm), second identical assembly for crosstalk test, USB-serial adapter, terminal or Python script to count bit errors.

1. **Assemble the IR link in the dock proxy.** Mount the TSAL6400 emitter and TSOP38238 demodulator in the printed or cardboard dock recess mockup so that emitter and receiver face each other across the simulated dock gap (≤ 5 mm). Wire emitter to ESP32 TX via 38 kHz RMT carrier (or function generator carrier + series resistor for current limit to 80 mA peak). Wire TSOP38238 output to ESP32 RX or USB-serial RX. Configure UART at 9600 baud.

2. **Indoor dim-light baseline.** With room lights off or shaded, transmit a 1000-byte test sequence (known pattern, e.g. `0xAA 0x55` repeating) via the IR link. On the receive side, count bytes received and compare to the known pattern. Record bit-error count.

3. **Worst-case ambient test.** Position the assembly under a south-facing window with direct sunlight striking the dock opening, OR aim a 1000 lux LED panel (measured at the dock aperture with a lux meter or phone app) at the assembly. Repeat the 1000-byte transmission. Record bit-error count.

4. **Record results.** Log both error counts in the table below. Convert to BER: BER = bit_errors / (bytes × 8).

5. **Crosstalk test.** Place a second identical emitter+TSOP38238 assembly 30 mm away (adjacent dock spacing on the 90 mm sphere geometry). Run both assemblies simultaneously, each transmitting a distinct known pattern. On each receiver, count any bytes that decode as the *other* assembly's pattern. Record cross-decode event count.

6. **Pass/fail.** **PASS:** 0 bit errors in dim-light baseline; ≤ 0.1 % BER (≤ 8 bit errors per 1000 bytes) in sunlit condition; 0 cross-decode events in crosstalk test. **FAIL on any criterion** → escalate to NFC fallback per CN-002; log failure condition in `cn002_ir_test_log.md`.

| Condition | Bytes Sent | Bit Errors | BER | Pass / Fail |
|-----------|----------:|----------:|----:|:-----------:|
| Dim-light baseline | 1000 | | | |
| Direct sunlight / 1000 lux | 1000 | | | |
| Crosstalk (cross-decode events) | — | — | — | |

**Overall: PASS / FAIL** — Date: _______ — Tester: _______

---

*End of BENCH_PROTOCOL.md*
