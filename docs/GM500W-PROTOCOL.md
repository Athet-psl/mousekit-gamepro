# GamePro GM500W (Instant 30fa:1440) vendor protocol

Recovered from the vendor app "Gaming Mouse 3.0.exe" (GM500 installer, Inno Setup 5.5.7),
by disassembling its `HidD_SetFeature` / `HidD_GetFeature` call sites, and checked on the device.
Cross-referenced with the Ant Esports GM333 driver (same 30fa:1440 chip), whose notes differ in places;
where they disagree, the GM500 app's code wins.

## Transport

- Interface 1 (`/dev/hidrawN` whose descriptor has usage page `0xFF01`, feature report `0x07`).
- Every command is an 8-byte feature report `07 CC b2 b3 b4 b5 b6 b7` (SET_FEATURE). The app sleeps 2 ms between reports.
- GET_FEATURE `0x07` returns a 32-byte status block (see below).
- Input report `0x06` on the same interface: `06 f8 xx` = DPI+, `06 f6 xx` = DPI−; `xx` = stage on press,
  `0x80 | new_stage` once applied. Stages 0–5 clamp at the ends.

## Status block (GET_FEATURE 0x07, 32 bytes)

| Byte | Meaning | Confidence |
|---|---|---|
| 4 | `0x32` = 50, matches `FIRE_TIME` (fire button interval) | guess |
| 6 | `0x03`, probably polling-rate code | guess |
| 7 | `(mode << 4) \| 9` | confirmed |
| 8 | `(mode << 4) \| speed` of the lighting being shown (all 16 modes) | confirmed (modes 2, 6, 7, 13) |
| 9 | follows the DPI stage in some lighting modes but drifts on its own in others (neon): **not** the DPI stage, use register 0x18 | confirmed |
| 11–12 | value that changes on its own (~5700–6000) | unknown |
| 17–18 | `5a a5` marker | — |

Factory lighting was mode 7 (Ambilight), speed 3, the same as the app's `config.ini` defaults (`LED_TYPE=7`, `LED_CYC_TIME=3`).

## Lighting (live, not saved until committed)

- **DPI stage colour** `07 14 (slot<<5)|G (R<<4)|B 00 00 00 00` (bit 4 clear), slots = DPI stages, 4-bit channels.
  **Channels are inverted: 0 = full on, 15 = off** (sending G=15, R=B=0 shows magenta). Confirmed.
  These are **not zones**: writing 8 different slots lit the whole mouse in the current stage's colour, and DPI+
  switched it to the next slot's. Static colour (mode 2) and DPI breathing show the current stage's slot; the
  mouse flashes it on a DPI change. There's no per-zone colour command (the GM333 notes' "zone streaming" is
  this same command with every slot set alike). Mousekit's smooth effects stream these slots.
- **Mode** `07 13 b2 b3 b4 b5 b6 b7` (app function 0x432030):
  - `b2 = 0x80 | colour_mask` (mask 0x7f = 7-colour cycle palette; 0 for single-colour modes and mode 13)
  - `b3 = 0x80 | (mode & 7) << 4 | (speed & 7)`: bit 7 = apply (without it the mouse keeps its current effect)
  - bit 3 of the mode goes in `b6 = 0x80` (modes 8–15). Verified: mode 13 "LEDs off" = `07 13 80 d3 09 04 80 02` turns the LEDs off.
    (Copying the app's `0x80 + (mode << 4)` arithmetic for modes ≥ 8 clears the apply bit and the mouse ignores the packet.)
  - `b4 = flag<<7 | toggle<<6 | (direction & 3)<<4 | 9`: bit 6 is a checkbox in the app (probably "symmetry"), bit 7 unknown, 9 = LEDs in this build (GM333 uses 11)
  - `b5` = brightness, sent as `7 − slider` (slider 1–7, so 0 = brightest); the app only offers it for modes 2, 3, 4, 5
  - speed (low 3 bits of `b3`) is the app's 6-step slider minus one (0–5); 7 turns the LEDs off. Not offered for modes 2, 9, 12, 13
  - `b7 = 0x02`
- Static green, verified: slots `R=15 G=0 B=15`, then `07 13 80 a0 19 04 00 02`.
- **Palette** `07 14 (slot<<5)|0x10|G (R<<4)|B …` (bit 4 set): the 7 colours animated modes draw from; `b2`'s mask picks the slots.
  Mono water (4) takes its colour from here, not from the zones: verified with slot 0 green and mask `0x01`.
- Direction (byte 4 bits 4–5): 0 clockwise, 1 anticlockwise (modes 3, 4, 5, 7, 10), 2 two-way (3, 4, 5), 3 overwrite (3 only).
  Symmetry (bit 6): modes 3, 4, 5, 7. From the app's control ids 45–50 in `skin_color.ini`.
- The firmware animates in zone steps (≈9 LEDs, 8 zones), so flowing effects look stepped; that's the hardware.

Mode IDs (app `LanguageText.ini` order, matches GM333 table): 0 DPI breathing, 1 cycle breathing, 2 light on (static),
3 flowing water, 4 mono water, 5 comet, 6 neon, 7 ambilight, 8 flicker, 9 star trek, 10 ripple, 11 enraptured,
12 button response, 13 LEDs off. The app only lists 0–13; the extra names in `LanguageText.ini` (14, 15) are for other models
and turn the GM500W's LEDs off.

## Saving to the mouse's memory (verified)

The vendor app saves by writing its whole config image into registers and then committing (fn 0x41a410):
- register write (fn 0x4139e0): `07 18 03 i aL aH data len-1` for each byte (staging), 4 ms, `07 18 09 00 aL aH 00 len-1`
  (store), `07 18 00 00 aL aH 00 00` (idle)
- commit (fn 0x413d30): `07 18 10 00 00 00 00 00`, 5 ms, `07 18 00 00 00 00 00 00`
- no checksum anywhere (fn 0x42f450, once mistaken for one, maps media-key indexes to HID consumer codes)

Live commands (07 13/07 14) don't touch the registers. After a commit, DPI values and the current stage take effect at
once, but the button table is only read at power-up: button changes need a replug (no live reload found yet). Verified: changing only register 0x1c from `f3` (ambilight) to
`e3` (neon), then committing, made the mouse come up in neon after a replug.

Stored config map (from the save routine and a register dump):

| Address | Contents |
|---|---|
| 0x00–0x07 | header `5a .. a5 ..` (constants) |
| 0x08–0x0f, 0x44–0x6c | button assignment tables (codes `21 22 23 24 …`, per profile) |
| 0x08–0x10 | 9 button codes `21 22 23 24 2f 2c 2f 2b f5` (`2f` = media key from the slot table) |
| 0x13 | bit n = bit 4 of stage n's DPI code |
| 0x14 | `08` |
| 0x15–0x17 | low nibbles of the 6 stages' DPI codes, two per byte (stage 0 in the high nibble) |
| 0x18 | `0x18 + current DPI stage` |
| 0x19 | enabled DPI stage mask (`3f`) |
| 0x1c | lighting: `0x80 \| (mode & 7) << 4 \| flag << 3 \| speed`; speed 7 = LEDs off; the app stores button response as mode 1 + flag |
| 0x1d | `0x80 \| palette mask` |
| 0x20–0x31 | 6 DPI stages × (R, G, B): low nibble = stage colour, high nibble = palette slot (inverted 4-bit) |
| 0x3a | `symmetry << 6 \| direction << 4 \| 9` |
| 0x3e, 0x3f | palette slot 7; 0x3f bits 4–6 = brightness byte |
| 0x98–0xcf | media-key slots (Forward = `b5` next track at 0xcb, Fire = `cd` play/pause at 0xdf) |
| 0x400+ | macros; 0xfa0+ a 16-byte signature string |

DPI codes (app table at 0x66b064, values from its macro code at 0x418190): codes 1–10 = 200–2000 in steps of 200,
`0c` = 2400, `0d` = 3200, `0e`–`17` = 4000–11200 in steps of 800, `18` = 12800 (`0b` unused). The mouse came with codes
6, 12, 13, 15, 17, 18 = 1200, 2400, 3200, 4800, 6400, 7200 DPI, which are the app's `config.ini` defaults. The live
`07 11` command is not DPI: the app brackets each apply with `07 11 02` and `07 11 00`.

Modes 8–11 (flicker, star trek, ripple, enraptured): the app's code stores `mode & 7`, the same as modes 0–3. Their real
stored encoding is not understood yet, so Mousekit doesn't save them.

## Other commands seen in the app (not tried yet)

| Cmd | Use in the app |
|---|---|
| `0x09` | 7 packed bit fields (fn 0x42f3b0, no direct callers found) |
| `0x0a` | one argument (fn 0x432200) |
| `0x0b`, `0x15`, `0x16` | block write: address/length, then 6-byte data chunks from a table, then end (fn 0x42fe00/0x430210) |
| `0x10` | key mapping (fns 0x437b40–0x437d60) |
| `0x11` | DPI configuration (fn 0x436350) |
| `0x12` | 16-bit value (fn 0x432690) |
| `0x18` | register access: `b2` flag bits; `03` = prepare read, `05` = read byte (then GET_FEATURE, value in byte 1), `10` = latch/commit, `00` = idle; `b3` = byte index, `b4 b5` = address LE, `b6` = data, `b7` = length−1 |
| `0x20` | puts the **factory** button/lighting/DPI settings into the running config (stored registers untouched; a replug brings the stored ones back). Verified: Forward came back as BTN_EXTRA, Fire as auto-click. Don't use as a "reload" |
| `0x21` + profile<<6 | macro/profile data (fn 0x4143f0) |

Register reads the app does: address `0x18`, 8 bytes, and a 32-byte block compared against a string (likely an ID check).
Register `0x18`, verified against four DPI button presses: byte 0 & 7 = current DPI stage, byte 1 = enabled-stage mask
(`3f` = 6 stages), seen as `19 3f 08 00 f3 ff 00 00`.
