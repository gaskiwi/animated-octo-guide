# CART.md — Week-1 P4.1 Connector Dev-Kit Purchase List

> **DRAFT — no purchases made. Any single item ≥ $250 requires human (Yoo) approval per guardrail §0.0-2. Total is well under that threshold. Yoo to review before ordering.**

| Item | Description | Qty | Est. USD/unit | Est. Line Total | Suggested Source / Part # | Notes |
|------|-------------|----:|-------------:|----------------:|---------------------------|-------|
| N52 disc magnets, 10 mm × 3 mm | Axially magnetised N52 discs for docking-face latch (connector side and node inserts) | 50 | $0.45 | $22.50 | K&J Magnetics D41A-N52 (or equivalent 50-pack) | Covers ~6 connector iterations + node-side insert mockups; sold in packs of 50 |
| MG90S metal-gear micro-servo | 9 g metal-gear servo for release lever and 2-DOF gimbal (2 axes/end × 2 ends = 4/strut); metal gear required for durability | 8 | $4.00 | $32.00 | AliExpress / Amazon — search "MG90S metal gear"; Tower Pro MG90S or clone | 4 for first strut assembly, 4 spares; plastic-gear variants are NOT acceptable |
| SI7201-B-00-IVR hall-effect switch | Omnipolar latching hall-effect switch for dock-occupancy sensing (plan §2.5); SOT-23-3 or through-hole | 10 | $1.50 | $15.00 | Mouser / DigiKey — Silicon Labs SI7201-B-00-IVR; alt: TI DRV5023 SOT-23 | 10 covers partial node mockup; add to order from DigiKey to hit free-shipping threshold |
| 940 nm IR emitter, ~100 mA | Carrier-modulated IR emitter for CN-002 Layer 1 UART-over-IR link; 940 nm, narrow beam preferred | 10 | $0.60 | $6.00 | DigiKey — Vishay TSAL6400 or SFH4545; TSAL6400 is 5 mm through-hole, easy to prototype | 6 active pairs + 4 spares |
| 940 nm IR photodiode, PIN | Matched receiver for above emitter; SFH309FA or equivalent narrow-angle PIN diode | 10 | $0.60 | $6.00 | DigiKey — Vishay SFH309FA-4 or TSPS34156 | Use with TSOP38238 for carrier demod; these are the bare diodes for custom receive circuits |
| TSOP38238 (or TSOP4838) IR demodulator | 38 kHz carrier demodulator IC; handles DC ambient rejection per CN-002 R1b risk; pairs with ESP32 UART+RMT carrier output | 8 | $1.40 | $11.20 | DigiKey — Vishay TSOP38238; alt TSOP4838 (38 kHz, same pinout) | 6 active, 2 spares; ESP32 RMT peripheral generates the 38 kHz carrier on TX side |
| M2/M3 stainless hex-socket screw assortment | For servo mounts, bracket assembly, and fixture work; M2×6, M2×8, M3×6, M3×10 with matching nuts | 1 kit | $7.00 | $7.00 | Amazon — "M2 M3 stainless hex socket assortment" 200–300 pc kit | One kit is sufficient; stainless preferred to avoid magnetisation near hall sensors |
| Digital luggage scale, 0–50 kg | F_pull bench measurement tool; 0.1 kg (≈1 N) resolution sufficient for 25–50 N target range | 1 | $12.00 | $12.00 | Amazon — any 50 kg digital luggage scale with peak-hold; e.g. Etekcity EL10 | **Mark: purchase only if not already on hand.** Peak-hold feature strongly preferred |
| Breadboard, jumper wires, 2.54 mm pin headers | For IR circuit prototyping: full-size breadboard, 40-pc M-M and M-F jumper sets, 40-pin 2.54 mm straight headers | 1 lot | $8.00 | $8.00 | Amazon / AliExpress — standard prototyping lot | If already stocked in lab, skip; estimated as one combined lot |

---

## TOTAL

| | | | | **$119.70** | | |
|-|-|-|-|------------|--|-|

**Well under the $250 guardrail threshold.**

### Trim log
No trims required at current quantities. If the luggage scale is already on hand, deduct $12.00 → **$107.70**. If breadboard/jumpers are stocked, deduct another $8.00 → **$99.70**.

### Ordering notes
- Consolidate DigiKey line items (SI7201, TSAL6400, SFH309FA, TSOP38238) into a single order to hit the $35 free-shipping threshold.
- K&J Magnetics ships fast from the US; order separately.
- Servos ship from overseas (7–14 days typical); order first if timeline is tight.
