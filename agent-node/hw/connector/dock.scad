// =============================================================================
// dock.scad — Discrete magnetic docking socket for FreeSN-derived swarm node
//
// Instantiated at each of 26 positions on a truncated-icosahedron shell grid.
// Node shell outer diameter: 90 mm.
//
// Self-centering geometry:
//   The recess has a chamfered (tapered) entry cone. When a mating connector
//   approaches within the capture envelope (±10 mm offset, ±20° angle), the
//   chamfer surface deflects the insert radially toward center while the N52
//   magnet pair closes the gap. The chamfer half-angle should be ≥ capture
//   angle (20°) so a tilted connector always has a normal-force component
//   pushing it toward axis.
//
// IR shroud (CN-002):
//   The recess floor is deep enough to keep the IR emitter/PD pair in shadow
//   from ambient light entering at angles outside the intended mating cone.
//   Each IR device sits in its own 3 mm through-hole centered ±ir_pair_offset
//   from the recess axis, drilled through the shell into the interior cavity.
//
// Pull-force target: F_pull(0°) ≈ 35 N (placeholder — replace with bench data
//   from axial pull test per BENCH_PROTOCOL.md before finalising magnet grade).
// =============================================================================

$fn = 64;

// ----------------------------------------------------------------------------
// Magnet parameters (N52 disc, one per dock face)
// ----------------------------------------------------------------------------
magnet_d       = 10.0;  // magnet diameter [mm]
magnet_h       =  3.0;  // magnet thickness [mm]
magnet_clear   =  0.15; // diametric clearance for press/retained fit [mm]

// ----------------------------------------------------------------------------
// Recess geometry
// ----------------------------------------------------------------------------
recess_depth   =  8.0;  // total depth of socket recess from shell outer face [mm]
                         // must be > magnet_h + shroud_depth
chamfer_angle  = 25.0;  // half-angle of entry chamfer cone [°]
                         // set ≥ capture angle (20°) for guaranteed self-centering
chamfer_depth  =  3.5;  // axial length of chamfer section [mm]
                         // drives the outer diameter of the chamfer mouth:
                         //   mouth_r = bore_r + chamfer_depth * tan(chamfer_angle)

// ----------------------------------------------------------------------------
// IR emitter / photodiode through-holes (CN-002 ambient-light shielding)
// ----------------------------------------------------------------------------
ir_hole_d      =  3.0;  // diameter of each IR through-hole [mm]
ir_pair_offset =  3.5;  // centre-to-centre half-spacing from recess axis [mm]
shroud_depth   =  4.0;  // min axial depth of flat bore above IR holes that
                         // acts as a light baffle; combined with recess_depth
                         // this sets the solid angle of sky the PD can see

// ----------------------------------------------------------------------------
// Insert (steel retention insert captured in shell)
// ----------------------------------------------------------------------------
wall_t          =  2.0;  // shell wall thickness around bore [mm]
                          // sets the bore outer-wall land; increase for higher
                          // pull-out strength
insert_flange_d = 16.0;  // outer diameter of insert flange (bears on shell face) [mm]
insert_flange_h =  1.5;  // flange height [mm]
insert_od       = 14.0;  // insert body outer diameter (fits into shell recess) [mm]
insert_h        =  6.0;  // insert body height (axial depth into shell) [mm]
insert_bore_d   = 10.3;  // insert inner bore (magnet pocket + clearance) [mm]
                          // = magnet_d + 2*magnet_clear

// ----------------------------------------------------------------------------
// Derived / convenience
// ----------------------------------------------------------------------------
// Bore radius (cylindrical section below chamfer)
bore_r = (magnet_d + 2 * magnet_clear) / 2;

// Chamfer mouth radius at shell outer face
mouth_r = bore_r + chamfer_depth * tan(chamfer_angle);

// =============================================================================
// Module: dock_recess()
//
// Negative (subtract) volume representing the socket cut into the shell.
// Origin: centre of the socket on the shell outer surface; Z− goes into shell.
//
// Geometry (top-to-bottom, Z = 0 at outer face, Z− into shell):
//   [0 .. −chamfer_depth]   : conical chamfer from mouth_r down to bore_r
//   [−chamfer_depth .. −recess_depth] : straight cylindrical bore
//   [−recess_depth .. −recess_depth−magnet_h] : magnet pocket (slightly tighter)
//   IR through-holes continue beyond recess_depth (pass-through to interior)
// =============================================================================
module dock_recess() {
    union() {
        // Entry chamfer cone — enables self-centering
        translate([0, 0, -chamfer_depth])
            cylinder(
                h  = chamfer_depth + 0.01,  // +epsilon to avoid z-fighting
                r1 = bore_r,
                r2 = mouth_r
            );

        // Straight bore (IR shroud section + magnet seating)
        translate([0, 0, -recess_depth])
            cylinder(h = recess_depth - chamfer_depth + 0.01, r = bore_r);

        // Magnet pocket — snug press fit (bore_r − magnet_clear keeps magnet)
        translate([0, 0, -recess_depth - magnet_h])
            cylinder(h = magnet_h + 0.01, r = magnet_d / 2 + magnet_clear / 2);

        // IR emitter through-hole (positive X side)
        translate([ir_pair_offset, 0, 1])   // +1 mm proud to pierce outer skin
            cylinder(h = recess_depth + magnet_h + 20, r = ir_hole_d / 2, center = false);
        translate([ir_pair_offset, 0, 1])
            mirror([0, 0, 1])
            cylinder(h = recess_depth + magnet_h + 20, r = ir_hole_d / 2);

        // IR photodiode through-hole (negative X side)
        translate([-ir_pair_offset, 0, 1])
            cylinder(h = recess_depth + magnet_h + 20, r = ir_hole_d / 2, center = false);
        translate([-ir_pair_offset, 0, 1])
            mirror([0, 0, 1])
            cylinder(h = recess_depth + magnet_h + 20, r = ir_hole_d / 2);
    }
}

// =============================================================================
// Module: dock_insert()
//
// The steel (or printed) insert that is press-fit or adhesive-bonded into the
// dock_recess void. It retains the N52 magnet and provides a wear surface.
//
// Origin: same as dock_recess — top face of flange at Z = 0.
// =============================================================================
module dock_insert() {
    difference() {
        union() {
            // Flange — bears on the shell outer face
            translate([0, 0, -insert_flange_h])
                cylinder(h = insert_flange_h, r = insert_flange_d / 2);

            // Body — sits inside the shell recess bore
            translate([0, 0, -insert_flange_h - insert_h])
                cylinder(h = insert_h, r = insert_od / 2);
        }

        // Magnet pocket inside insert
        translate([0, 0, -insert_flange_h - insert_h + 0.01])
            cylinder(h = magnet_h + 0.5, r = insert_bore_d / 2);

        // IR pass-through holes aligned with shell holes
        translate([ir_pair_offset, 0, 1])
            cylinder(h = insert_flange_h + insert_h + 2, r = ir_hole_d / 2, center = false);
        translate([ir_pair_offset, 0, 1])
            mirror([0, 0, 1])
            cylinder(h = insert_flange_h + insert_h + 2, r = ir_hole_d / 2);

        translate([-ir_pair_offset, 0, 1])
            cylinder(h = insert_flange_h + insert_h + 2, r = ir_hole_d / 2, center = false);
        translate([-ir_pair_offset, 0, 1])
            mirror([0, 0, 1])
            cylinder(h = insert_flange_h + insert_h + 2, r = ir_hole_d / 2);
    }
}

// =============================================================================
// Module: dock_assembly()
//
// Visual check: shows a representative shell-wall slice, the recess subtracted
// from it, and the insert positioned in place. Colour-coded for clarity.
// Not used in production boolean operations — use dock_recess() as a negative
// and dock_insert() as a positive in your shell model.
// =============================================================================
module dock_assembly() {
    shell_slice_t = 12;  // representative shell wall thickness for visualisation

    // Shell slice (grey)
    color("silver", 0.6)
    difference() {
        translate([0, 0, -shell_slice_t])
            cylinder(h = shell_slice_t, r = insert_flange_d / 2 + wall_t + 2);
        dock_recess();
    }

    // Insert (steel blue)
    color("steelblue", 0.9)
    dock_insert();

    // Magnet shown seated in insert pocket (red)
    color("red", 0.85)
    translate([0, 0, -insert_flange_h - magnet_h])
        cylinder(h = magnet_h, r = magnet_d / 2);
}

// =============================================================================
// Default render
// =============================================================================
dock_assembly();
