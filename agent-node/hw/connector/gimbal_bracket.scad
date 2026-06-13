// gimbal_bracket.scad
// 2-DOF pan/tilt gimbal bracket — connector-base ↔ strut-body interface
// Master plan §5.2 P4.1, §2.2
//
// TORQUE BUDGET (read before printing):
//   Required joint torque  : >= 0.8 N·m  (master plan §5.2, 350 g @ 220 mm)
//   MG90S stall torque     : ~1.8 kg·cm  = ~0.177 N·m at servo shaft
//   Raw deficit            : 0.8 / 0.177 ≈ 4.52×  =>  gear_ratio default = 5
//   With gear_ratio = 5    : 5 × 0.177   = 0.885 N·m  (meets requirement)
//
//   *** WARNING: this bracket is structural frame only. ***
//   The gear_ratio parameter is a PLACEHOLDER. A physical reduction stage
//   (external gearbox, printed planetary gearset, or belt/pulley stage)
//   MUST be implemented as a separate sub-assembly at each servo output
//   before the 0.8 N·m torque requirement is satisfied.
//   The bracket alone does NOT provide torque multiplication.

$fn = 48;

// ── Servo (MG90S-class) ─────────────────────────────────────────────────────
servo_body_w    = 22.5;   // body length along ear axis (mm)
servo_body_d    = 12.5;   // body depth (mm)
servo_body_h    = 23.5;   // body height, base to top face (mm)
servo_shaft_dia =  4.8;   // output shaft / spline OD (mm)
servo_shaft_ext =  4.0;   // shaft protrusion above body top face (mm)
servo_ear_span  = 32.5;   // ear-to-ear total width (mm)
servo_ear_t     =  2.5;   // mounting ear/tab thickness (mm)
servo_ear_screw =  2.5;   // M2.5 through ear mounting screw diameter (mm)
servo_horn_r    = 12.0;   // single-arm horn tip radius from shaft center (mm)

// ── Structural geometry ─────────────────────────────────────────────────────
tube_od           = 20.0;  // strut tube outer diameter (mm)
tube_wall         =  2.0;  // tube wall thickness for stub visualization (mm)
connector_base_d  = 30.0;  // output connector base plate diameter (mm)
connector_base_t  =  3.5;  // connector base plate thickness (mm)
connector_pcd     = 20.0;  // connector bolt-circle diameter (mm)

// ── Bracket structure ───────────────────────────────────────────────────────
bracket_wall_t  =  3.0;   // general wall thickness (mm); >=2.8 for FDM strength
pan_clearance   =  0.45;  // fit clearance around pan-axis rotating parts (mm)
tilt_clearance  =  0.45;  // fit clearance around tilt-axis rotating parts (mm)
screw_d         =  3.2;   // M3 structural screw clearance diameter (mm)
screw_head_d    =  6.0;   // M3 hex/pan head diameter (mm)
tube_clamp_gap  =  1.2;   // split-clamp slot width (mm)

// ── Torque / gear-ratio placeholder ────────────────────────────────────────
// gear_ratio represents the reduction ratio of the external drive stage that
// MUST be physically implemented before the 0.8 N·m requirement is met.
// Required: gear_ratio >= 4.52 (use >= 5 for margin).
// Implement as: printed planetary gearset, commercial servo gearbox, or
// toothed-belt/pulley stage sized for 0.3 N·m continuous input.
gear_ratio = 5;   // placeholder — no physical reduction in this bracket

// ── Internal derived values ─────────────────────────────────────────────────
_pan_blk_w   = servo_body_w + bracket_wall_t * 2;
_pan_blk_d   = servo_body_d + bracket_wall_t * 2;
_pan_blk_h   = servo_body_h + bracket_wall_t;      // open top for shaft exit
_tilt_blk_w  = servo_body_h + bracket_wall_t;       // X span of U-bracket
_tilt_blk_d  = servo_body_d + bracket_wall_t * 2;
_tilt_blk_h  = servo_body_w + bracket_wall_t * 2;   // Z span


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: strut_tube_stub
//   Visualization placeholder for the strut tube end.
//   Not a structural part of the gimbal; provides assembly context.
// ══════════════════════════════════════════════════════════════════════════════
module strut_tube_stub(len = 35) {
    difference() {
        cylinder(d = tube_od, h = len);
        translate([0, 0, -0.1])
            cylinder(d = tube_od - tube_wall * 2, h = len + 0.2);
    }
}


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: pan_servo_mount
//   Pocket block that holds the pan (yaw) servo with shaft pointing +Z.
//   Bolts to the tube-clamp base.  Servo ears are recessed flush.
//   Origin: center of block, Z=0 at bottom face.
//
//   PRINT NOTES:
//   - No overhangs >45° on exterior faces.
//   - Interior ear-relief slot underside: ~90° overhang.
//     Recommend printing with servo-pocket facing UP; add 2-perimeter bridge
//     supports inside the pocket only (slicer "support on build plate" OFF).
// ══════════════════════════════════════════════════════════════════════════════
module pan_servo_mount() {
    wt = bracket_wall_t;

    difference() {
        // Outer block
        translate([0, 0, _pan_blk_h / 2])
            cube([_pan_blk_w, _pan_blk_d, _pan_blk_h], center = true);

        // Servo body pocket — open at +Z face for shaft exit
        translate([0, 0, wt + (servo_body_h) / 2 - 0.01])
            cube([servo_body_w + pan_clearance,
                  servo_body_d + pan_clearance,
                  servo_body_h + 0.2],
                 center = true);

        // Servo ear (tab) relief slots — pair on ±X faces
        // OVERHANG: bottom of each slot is a horizontal surface (~90°).
        // Bridgeable if slot width <= 15 mm; otherwise add support.
        for (sx = [-1, 1])
            translate([sx * (servo_body_w / 2 + pan_clearance / 2),
                       0,
                       wt + servo_ear_t / 2 + pan_clearance / 2])
                cube([servo_ear_span - servo_body_w + pan_clearance,
                      servo_body_d + pan_clearance,
                      servo_ear_t + pan_clearance],
                     center = true);

        // M2.5 screw holes through each ear pocket
        for (sx = [-1, 1])
            translate([sx * (servo_ear_span / 2),
                       0,
                       wt / 2])
                cylinder(d = servo_ear_screw, h = wt + 1, center = true);

        // Pan shaft bore through top face (clearance for shaft + gearbox input)
        translate([0, 0, _pan_blk_h - wt / 2])
            cylinder(d = servo_shaft_dia + pan_clearance * 2,
                     h = wt + servo_shaft_ext + 1,
                     center = true);

        // M3 mounting screw holes (bottom face → base plate)
        for (mx = [-1, 1], my = [-1, 1])
            translate([mx * (servo_body_w / 2 - screw_d),
                       my * (servo_body_d / 2 - screw_d),
                       wt / 2 - 0.1])
                cylinder(d = screw_d, h = wt + 0.2, center = true);
    }
}


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: tilt_servo_mount
//   U-bracket holding the tilt (pitch) servo with shaft pointing +X.
//   Mounts on the pan-rotation output plate.  Connector base plate hangs off
//   the +X (shaft) side via horn or gearbox flange.
//   Origin: center of U-bracket block, Z=0 at bottom face.
//
//   PRINT NOTES:
//   - U-bracket ceiling (inner top face) is a horizontal overhang (90°).
//     FLAG: print this part lying on its side (servo pocket facing +Y or -Y)
//     to eliminate the horizontal ceiling overhang.  In that orientation all
//     overhangs are <= 45°.
//   - If printed upright, bridging support required inside U-cavity.
// ══════════════════════════════════════════════════════════════════════════════
module tilt_servo_mount() {
    wt = bracket_wall_t;

    difference() {
        // Outer U-block; X = servo_body_h axis, Z = servo_body_w axis
        translate([0, 0, _tilt_blk_h / 2])
            cube([_tilt_blk_w, _tilt_blk_d, _tilt_blk_h], center = true);

        // Inner pocket — open on +X face (shaft / gearbox output side)
        translate([wt / 2, 0, _tilt_blk_h / 2])
            cube([servo_body_h + tilt_clearance,
                  servo_body_d + tilt_clearance,
                  servo_body_w + tilt_clearance],
                 center = true);

        // Servo ear tab slots (ears span ±Z inside U)
        // OVERHANG FLAG: lower ear slot floor at 90° if printed upright.
        for (sz = [-1, 1])
            translate([-wt / 2,
                       0,
                       sz * (servo_body_w / 2) + _tilt_blk_h / 2])
                cube([servo_ear_t + tilt_clearance,
                      servo_ear_span + tilt_clearance,
                      servo_ear_t + tilt_clearance],
                     center = true);

        // M2.5 ear mounting screw holes (Z-axis, through U-bracket walls)
        for (sy = [-1, 1])
            translate([-servo_body_h / 2,
                       sy * (servo_ear_span / 2),
                       _tilt_blk_h / 2])
                cylinder(d = servo_ear_screw, h = _tilt_blk_h + 1, center = true);

        // Tilt shaft bore on -X face (shaft enters from back; gearbox on +X)
        translate([-(_tilt_blk_w / 2) + wt / 2, 0, _tilt_blk_h / 2])
            rotate([0, 90, 0])
                cylinder(d = servo_shaft_dia + tilt_clearance * 2,
                         h = wt + 1,
                         center = true);

        // M3 base mounting holes (bottom face)
        for (mx = [-1, 1], my = [-1, 1])
            translate([mx * (servo_body_h / 2 - screw_d * 1.5),
                       my * (servo_body_d / 2 - screw_d),
                       wt / 2 - 0.1])
                cylinder(d = screw_d, h = wt + 0.2, center = true);
    }
}


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: connector_base_plate
//   30 mm disc that mates with the dock mechanism.
//   Sits on tilt-servo output (or gearbox flange on +X side of tilt mount).
//   Origin: bottom center face, +Z is outward face toward dock.
//
//   PRINT NOTES:  flat disc — no overhangs; print face-down.
// ══════════════════════════════════════════════════════════════════════════════
module connector_base_plate() {
    difference() {
        // Main disc
        cylinder(d = connector_base_d, h = connector_base_t);

        // Central shaft / gearbox output bore
        translate([0, 0, -0.1])
            cylinder(d = servo_shaft_dia + tilt_clearance * 2,
                     h = connector_base_t + 0.2);

        // Bolt circle — 4× M3, on connector_pcd diameter
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a])
                translate([connector_pcd / 2, 0, -0.1])
                    cylinder(d = screw_d, h = connector_base_t + 0.2);

        // Countersink relief (M3 pan-head flush)
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a])
                translate([connector_pcd / 2, 0, connector_base_t - 1.2])
                    cylinder(d = screw_head_d, h = 1.3);

        // Anti-rotation flat (chord cut, prevents rotation on horn spline)
        translate([connector_base_d / 2 - 1.0, -connector_base_d,
                   -0.1])
            cube([connector_base_d, connector_base_d * 2,
                  connector_base_t + 0.2]);
    }
}


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: _tube_clamp_base  (internal helper)
//   Split-clamp ring that grips the strut tube OD.
//   Bracket pan-mount block attaches to its top face.
// ══════════════════════════════════════════════════════════════════════════════
module _tube_clamp_base(clamp_h = 18) {
    wt  = bracket_wall_t;
    od  = tube_od + wt * 2;
    mid = _pan_blk_w;  // match pan mount footprint in X

    difference() {
        union() {
            // Clamp ring
            cylinder(d = od, h = clamp_h);
            // Rectangular pad on top for pan_servo_mount footprint
            translate([0, 0, clamp_h - 0.1])
                cube([mid, _pan_blk_d, wt + 0.1], center = true);
        }
        // Tube bore
        translate([0, 0, -0.1])
            cylinder(d = tube_od + pan_clearance, h = clamp_h + 0.2);
        // Split-clamp slot — one side, tighten with M3 screw
        translate([od / 2, -tube_clamp_gap / 2, -0.1])
            cube([od, tube_clamp_gap, clamp_h + 0.2]);
        // M3 clamp screw hole (radial, through clamp body)
        translate([0, -(od / 2 + 1), clamp_h / 2])
            rotate([90, 0, 0])
                cylinder(d = screw_d, h = od + 2, center = true);
        // M3 clamp nut pocket (hex, on far side)
        translate([0, od / 2 - 5, clamp_h / 2])
            rotate([90, 0, 0])
                cylinder(d = 6.4, h = 3.5, $fn = 6, center = true);
    }
}


// ══════════════════════════════════════════════════════════════════════════════
// MODULE: gimbal_assembly
//   Full assembly at neutral position: pan = 0° (yaw), tilt = 0° (pitch).
//   Z = 0 is the strut tube top face / clamp base bottom face.
//
//   Assembly stack (bottom → top / output):
//     [0] strut_tube_stub     — strut tube visualization, Z = -35 to 0
//     [1] _tube_clamp_base    — clamps to tube OD, top pad at Z = clamp_h
//     [2] pan_servo_mount     — shaft at +Z (yaw output), above clamp pad
//     [3] pan rotation plate  — thin disc rotating with pan output
//     [4] tilt_servo_mount    — shaft at +X (pitch output), above pan plate
//     [5] connector_base_plate — at +X of tilt servo shaft (dock interface)
//
//   GEAR RATIO REMINDER (see top-of-file torque budget comment):
//   A gear_ratio = 5 reduction stage must be inserted at the output of
//   EACH servo before this assembly meets the 0.8 N·m requirement.
//   This assembly renders as if the servos drive joints directly.
// ══════════════════════════════════════════════════════════════════════════════
module gimbal_assembly() {
    clamp_h   = 18;
    wt        = bracket_wall_t;

    // ── [0] Strut tube stub ───────────────────────────────────────────────
    color("Silver", 0.55)
        translate([0, 0, -35])
            strut_tube_stub(35);

    // ── [1] Tube clamp base ───────────────────────────────────────────────
    color("SaddleBrown", 0.8)
        _tube_clamp_base(clamp_h);

    // ── [2] Pan servo mount ───────────────────────────────────────────────
    // Bottom of pan mount sits on clamp pad top face.
    pan_z0 = clamp_h;
    color("SteelBlue", 0.88)
        translate([0, 0, pan_z0])
            pan_servo_mount();

    // ── [3] Pan rotation output disc ─────────────────────────────────────
    // Thin disc centered on shaft axis; represents gear-stage output flange.
    // In real hardware: output gear / horn / belt sprocket lives here.
    pan_rot_z = pan_z0 + _pan_blk_h + servo_shaft_ext;
    color("DarkGoldenrod", 0.7)
        translate([0, 0, pan_rot_z])
            difference() {
                cylinder(d = servo_horn_r * 2, h = wt);
                translate([0, 0, -0.1])
                    cylinder(d = servo_shaft_dia + pan_clearance * 2,
                             h = wt + 0.2);
            }

    // ── [4] Tilt servo mount ──────────────────────────────────────────────
    // Sits on pan rotation disc; shaft points +X for pitch motion.
    tilt_z0 = pan_rot_z + wt;
    color("CornflowerBlue", 0.88)
        translate([0, 0, tilt_z0])
            tilt_servo_mount();

    // ── [5] Connector base plate (dock interface) ─────────────────────────
    // At the +X shaft output of the tilt servo, rotated 90° about Y.
    conn_x = _tilt_blk_w / 2 + connector_base_t;
    color("Gold", 0.9)
        translate([conn_x, 0, tilt_z0 + _tilt_blk_h / 2])
            rotate([0, 90, 0])
                connector_base_plate();

    // ── Gear-ratio placeholder callout geometry ───────────────────────────
    // Two translucent cylinders mark where reduction stages must be inserted.
    // Remove these for final assembly export; keep for design review.
    //
    // Pan-axis stage (between pan servo shaft and pan rotation disc):
    color("OrangeRed", 0.25)
        translate([0, 0, pan_z0 + _pan_blk_h])
            cylinder(d = servo_horn_r * 1.4, h = servo_shaft_ext + wt);
    // Tilt-axis stage (between tilt servo shaft and connector base):
    color("OrangeRed", 0.25)
        translate([_tilt_blk_w / 2, 0, tilt_z0 + _tilt_blk_h / 2])
            rotate([0, 90, 0])
                cylinder(d = servo_horn_r * 1.4, h = connector_base_t + 4);
}


// ─── Default render ───────────────────────────────────────────────────────────
gimbal_assembly();
