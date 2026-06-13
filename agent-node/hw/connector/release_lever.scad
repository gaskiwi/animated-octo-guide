// release_lever.scad
// Magnetic-release lever mechanism for strut connector head.
//
// Peel geometry rationale:
//   A 10 mm N52 disc magnet (3 mm thick) can exert 3–5 N of direct pull force.
//   Fighting that force axially requires the servo to produce an equivalent linear
//   force over a very short stroke, which exceeds the MG90S torque budget at the
//   short moment arms available inside the 30×30×20 mm envelope.
//   Instead, a cam-driven lever tilts the magnet at one edge, peeling it off the
//   ferrous face. Peeling initiates separation at a single contact line and
//   propagates; the force required is typically 20–40% of the direct pull force.
//   The servo rotates the cam, the cam pushes the lever tip under the magnet edge,
//   and the lever pivots about a hinge pin — trading servo rotation for mechanical
//   advantage.

$fn = 48;

// ─────────────────────────────────────────────────────────────
//  PARAMETERS
// ─────────────────────────────────────────────────────────────

// MG90S servo body (bounding box, mm)
servo_body_w  = 22.8;   // X — width across the servo face
servo_body_d  = 12.5;   // Y — body depth (ear to ear not included)
servo_body_h  = 35.5;   // Z — full height including bottom mounting ears

// Servo output shaft
spline_d      = 4.8;    // diameter of 25T output spline (mm)
spline_h      = 3.5;    // exposed spline height above body top

// Cam / crank geometry (press-fit or screw-on servo horn replacement)
cam_radius    = 8.0;    // distance from spline center to cam lobe tip (mm)
cam_lobe_w    = 4.0;    // width of cam lobe (mm)
cam_thickness = 3.0;    // cam disk thickness (mm)
cam_bore_d    = spline_d + 0.15;  // light press-fit on spline

// Lever arm
lever_length    = 22.0;  // pivot-to-tip length (mm)
lever_thickness =  3.5;  // lever thickness in Z (mm)
lever_width     =  4.0;  // lever width in Y (mm)
lever_tip_r     =  1.5;  // rounded tip radius

// Hinge / pivot pin
hinge_pin_d   = 2.5;    // M2.5 pin or printed-in stub
hinge_wall    = 1.5;    // wall around pin bore

// Cam–lever interface
cam_follower_d = 3.0;   // diameter of the roller/nub on the lever that contacts the cam

// 10 mm N52 disc magnet
magnet_d      = 10.0;
magnet_h      =  3.0;
magnet_recess =  1.0;   // how deep the magnet sits below connector face

// Peel angle — lever tip lifts this many degrees at full stroke
peel_angle    = 18.0;   // deg; peeling starts well before full angle

// Connector head envelope (for reference / clearance checks)
envelope_x    = 30.0;
envelope_y    = 30.0;
envelope_z    = 20.0;

// Wall / structural thickness
wall_t        = 1.6;    // minimum printable wall (2 perimeters @ 0.4 mm nozzle)

// Servo mounting offset inside envelope
servo_x_offset = -(envelope_x/2 - servo_body_w/2 - wall_t);
servo_z_offset = -(envelope_z/2 - servo_body_h/2 + 2);

// ─────────────────────────────────────────────────────────────
//  MODULE: mg90s_servo_body
//  Simplified bounding-box placeholder for fit-checking.
//  NOT a detailed model — just the critical envelope + spline stub.
//  Overhang note: the real servo has no critical overhangs;
//  this placeholder is solid and prints trivially.
// ─────────────────────────────────────────────────────────────
module mg90s_servo_body() {
    color("DimGray", 0.7) {
        // Main body block
        translate([-servo_body_w/2, -servo_body_d/2, 0])
            cube([servo_body_w, servo_body_d, servo_body_h]);

        // Mounting ear tabs (simplified — flat flanges at Z=0)
        // Ears extend +/-6 mm in X at the bottom 3 mm
        for (sx = [-1, 1])
            translate([sx * (servo_body_w/2), -servo_body_d/2, 0])
                cube([6, servo_body_d, 3]);

        // Output spline stub on top
        translate([0, 0, servo_body_h])
            cylinder(d = spline_d, h = spline_h);

        // Small output shaft hub (visible collar)
        translate([0, 0, servo_body_h])
            cylinder(d = spline_d + 2.5, h = 1.5);
    }
}

// ─────────────────────────────────────────────────────────────
//  MODULE: release_cam
//  Disk cam that presses the lever when the servo rotates.
//  Sits on the servo spline (cam_bore_d press/clearance fit).
//
//  Geometry: circular disk of radius cam_radius with an
//  off-center lobe. At the neutral (latched) position the lobe
//  is retracted from the lever follower. Servo rotates ~peel_angle
//  to drive the lobe into the follower nub on the lever.
//
//  Overhang: cam is printed flat (cam_thickness in Z, disk in XY).
//  No overhangs. Spline bore needs support only if printed upright;
//  recommend printing lying flat.
// ─────────────────────────────────────────────────────────────
module release_cam() {
    color("SteelBlue") {
        difference() {
            union() {
                // Main cam disk
                cylinder(d = cam_radius * 2, h = cam_thickness);

                // Lobe: an eccentric bump that contacts the lever follower.
                // Placed at +X from the spline center.
                // Height of lobe above disk face = cam_follower_d / 2
                // so the lever follower rides up onto it smoothly.
                translate([cam_radius - cam_lobe_w/2, 0, 0])
                    hull() {
                        cylinder(d = cam_lobe_w, h = cam_thickness);
                        translate([cam_lobe_w/2, 0, 0])
                            cylinder(d = cam_lobe_w * 0.6, h = cam_thickness);
                    }
            }

            // Spline bore (light press-fit)
            translate([0, 0, -0.1])
                cylinder(d = cam_bore_d, h = cam_thickness + 0.2);

            // Anti-rotation flat (matches 25T spline flat side, simplified)
            translate([cam_bore_d/2 - 0.4, -cam_bore_d/2, -0.1])
                cube([1.0, cam_bore_d, cam_thickness + 0.2]);
        }
    }
}

// ─────────────────────────────────────────────────────────────
//  MODULE: release_lever
//  The lever arm. Pivots on a hinge pin at one end; the cam
//  follower nub sits near the pivot; the tip contacts the magnet
//  edge at the far end.
//
//  Coordinate convention (local):
//    Origin at hinge pin center.
//    Lever extends in +X.
//    Lever lies in XY plane; thickness in Z.
//
//  Overhang: lever printed lying flat — no overhangs.
//  Hinge knuckle has a 180° arc; print orientation should keep the
//  bore horizontal if unsupported (bridging ≤ hinge_pin_d ≈ 2.5 mm,
//  within FDM bridge capability).
//
//  The tip is a rounded wedge so it can slip under the magnet edge
//  without catching on the connector face chamfer.
// ─────────────────────────────────────────────────────────────
module release_lever() {
    color("Coral") {
        difference() {
            union() {
                // Hinge knuckle (thickened cylinder around pin bore)
                cylinder(d = hinge_pin_d + 2*hinge_wall, h = lever_thickness);

                // Main lever body — tapered slightly toward the tip for stiffness
                hull() {
                    // Root, near hinge
                    translate([0, -(lever_width/2), 0])
                        cube([0.1, lever_width, lever_thickness]);

                    // Tip, at lever_length
                    translate([lever_length - lever_tip_r, -(lever_width/2 * 0.7), 0])
                        cube([0.1, lever_width * 0.7, lever_thickness]);
                }

                // Rounded tip wedge (contacts magnet edge — thin leading edge)
                translate([lever_length - lever_tip_r, 0, 0])
                    cylinder(r = lever_tip_r, h = lever_thickness);

                // Cam follower nub — sits at cam_radius from spline center.
                // Positioned at X = (cam_radius - distance from hinge to spline)
                // For assembly the hinge is offset so this nub aligns with the cam lobe.
                translate([cam_radius - cam_lobe_w/2, 0, lever_thickness])
                    cylinder(d = cam_follower_d, h = cam_follower_d/2);
            }

            // Hinge pin bore
            translate([0, 0, -0.1])
                cylinder(d = hinge_pin_d + 0.2, h = lever_thickness + 0.2);
        }
    }
}

// ─────────────────────────────────────────────────────────────
//  MODULE: release_assembly
//  Shows all parts in the neutral (latched) position.
//  The magnet is shown as a red disk seated in the connector face.
//  The lever tip is just beneath the magnet edge — zero preload.
//  When the servo rotates +peel_angle, the cam lobe pushes the
//  follower nub, rotating the lever about its hinge pin, driving
//  the lever tip upward under the magnet edge and peeling it off.
//
//  Envelope reference box shown as a ghost outline.
// ─────────────────────────────────────────────────────────────
module release_assembly() {
    // ── Envelope ghost ──────────────────────────────────────
    color("LightGray", 0.12)
        translate([-envelope_x/2, -envelope_y/2, -envelope_z/2])
            cube([envelope_x, envelope_y, envelope_z]);

    // ── Servo body ──────────────────────────────────────────
    // Mounted at the back of the envelope, shaft pointing +Z (up).
    // Offset so the spline is near the cam centerline.
    translate([servo_x_offset, 0, servo_z_offset])
        mg90s_servo_body();

    // ── Cam (on spline) ─────────────────────────────────────
    // Z position: top of servo body + spline_h clearance so cam
    // clears the hub collar.
    cam_z = servo_z_offset + servo_body_h + spline_h - cam_thickness/2;
    translate([servo_x_offset, 0, cam_z])
        release_cam();

    // ── Lever ────────────────────────────────────────────────
    // Hinge pin is at the same X as the cam center so the follower
    // nub aligns with the cam lobe at the neutral position.
    // Lever extends toward the magnet (+X in world coords from here).
    hinge_x = servo_x_offset;
    hinge_y = -(lever_width/2 + cam_lobe_w/2 + 0.5); // clears cam in Y
    hinge_z = cam_z - cam_thickness/2 - lever_thickness - 0.3;

    translate([hinge_x, hinge_y, hinge_z])
        release_lever();

    // ── Magnet ───────────────────────────────────────────────
    // Seated in connector face (top of envelope, XY center offset to
    // align with lever tip).
    magnet_x = hinge_x + lever_length;
    color("Red", 0.8)
        translate([magnet_x, 0, envelope_z/2 - magnet_h + magnet_recess])
            cylinder(d = magnet_d, h = magnet_h);

    // ── Hinge pin (visual reference) ─────────────────────────
    color("Silver")
        translate([hinge_x, hinge_y, hinge_z - 1])
            cylinder(d = hinge_pin_d, h = lever_thickness + 2);
}

// ─────────────────────────────────────────────────────────────
//  RENDER
// ─────────────────────────────────────────────────────────────
release_assembly();
