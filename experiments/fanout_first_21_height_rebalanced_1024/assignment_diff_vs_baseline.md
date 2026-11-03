# 21-height rebalanced 1024 assignment — diff vs the 18-layer baseline

* new run dir: `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`
* baseline run dir (read-only): `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024`
* baseline assignment sha256: `4ad5af2d40cf37f5a379567453301bc392f04c0607ffaffacd6431a43602c064`

## 1. Plane counts (baseline 18 planes -> new 21 planes)

| plane (new) | label | z (mm) | routes |
|---|---|---:|---:|
| 2 | L2 | -0.35 | 0 |
| 3 | L3 | -0.30 | 0 |
| 4 | L4 | -0.25 | 0 |
| 5 | L5 | -0.20 | 0 |
| 6 | L6 | -0.15 | 0 |
| 7 | L7 | -0.10 | 0 |
| 20 | L20 | -0.05 | 0 |
| 1001 | Z1_INTERFACE | +0.00 | 0 |
| 8 | L8 | +0.05 | 0 |
| 9 | L9 | +0.10 | 0 |
| 10 | L10 | +0.15 | 0 |
| 11 | L11 | +0.20 | 0 |
| 12 | L12 | +0.25 | 0 |
| 13 | L13 | +0.30 | 0 |
| 14 | L14 | +0.35 | 0 |
| 15 | L15 | +0.40 | 0 |
| 16 | L16 | +0.45 | 0 |
| 1002 | Z2_INTERFACE | +0.50 | 0 |
| 17 | L17 | +0.55 | 0 |
| 18 | L18 | +0.60 | 0 |
| 19 | L19 | +0.65 | 0 |

| old layer | baseline routes |
|---|---:|
| L2 | 1 |
| L3 | 1 |
| L4 | 1 |
| L5 | 1 |
| L6 | 1 |
| L7 | 1 |
| L8 | 1 |
| L9 | 1 |
| L10 | 1 |
| L11 | 1 |
| L12 | 1 |
| L13 | 1 |
| L14 | 1 |
| L15 | 1 |
| L16 | 1 |
| L17 | 1 |
| L18 | 1 |
| L19 | 1 |

## 2. Manual groups (fixed)

| group | routes | new plane | old planes | plane id unchanged | old z | new z |
|---|---:|---:|---|---|---|---:|
| Z1-U1 | 64 | 2 (L2) | [2] | True | [-0.35] | -0.35 |
| Z1-U2 | 64 | 3 (L3) | [3] | True | [-0.29] | -0.30 |
| Z1-U3 | 64 | 4 (L4) | [4] | True | [-0.23] | -0.25 |
| Z1-U4 | 64 | 5 (L5) | [5] | True | [-0.17] | -0.20 |
| Z2-U1 | 16 | 10 (L10) | [10] | True | [0.15] | +0.15 |
| Z2-U2 | 16 | 11 (L11) | [11] | True | [0.2] | +0.20 |
| Z2-U3 | 40 | 12 (L12) | [12] | True | [0.25] | +0.25 |
| Z2-U4 | 40 | 13 (L13) | [13] | True | [0.3] | +0.30 |

## 3. Z1 other (64 C4 opposite orbits, sorted by group_id)

plan: 6:13 7:13 20:13 1001:13 8:12

| orbit index | c4 group | old layer | new plane |
|---:|---:|---:|---:|
| 0 | 1 | 6 | 6 |
| 1 | 2 | 6 | 6 |
| 2 | 3 | 6 | 6 |
| 3 | 4 | 6 | 6 |
| 4 | 5 | 6 | 6 |
| 5 | 6 | 6 | 6 |
| 6 | 7 | 6 | 6 |
| 7 | 8 | 6 | 6 |
| 8 | 9 | 6 | 6 |
| 9 | 10 | 6 | 6 |
| 10 | 11 | 6 | 6 |
| 11 | 12 | 6 | 6 |
| 12 | 13 | 6 | 6 |
| 13 | 14 | 6 | 7 |
| 14 | 15 | 6 | 7 |
| 15 | 24 | 6 | 7 |
| 16 | 25 | 6 | 7 |
| 17 | 26 | 6 | 7 |
| 18 | 27 | 6 | 7 |
| 19 | 28 | 6 | 7 |
| 20 | 29 | 6 | 7 |
| 21 | 30 | 6 | 7 |
| 22 | 31 | 6 | 7 |
| 23 | 32 | 6 | 7 |
| 24 | 33 | 6 | 7 |
| 25 | 34 | 6 | 7 |
| 26 | 35 | 6 | 20 |
| 27 | 36 | 6 | 20 |
| 28 | 37 | 6 | 20 |
| 29 | 94 | 6 | 20 |
| 30 | 95 | 6 | 20 |
| 31 | 96 | 6 | 20 |
| 32 | 97 | 7 | 20 |
| 33 | 98 | 7 | 20 |
| 34 | 99 | 7 | 20 |
| 35 | 100 | 7 | 20 |
| 36 | 101 | 7 | 20 |
| 37 | 102 | 7 | 20 |
| 38 | 103 | 7 | 20 |
| 39 | 104 | 7 | 1001 |
| 40 | 105 | 7 | 1001 |
| 41 | 106 | 7 | 1001 |
| 42 | 107 | 7 | 1001 |
| 43 | 108 | 7 | 1001 |
| 44 | 109 | 7 | 1001 |
| 45 | 110 | 7 | 1001 |
| 46 | 111 | 7 | 1001 |
| 47 | 112 | 7 | 1001 |
| 48 | 113 | 7 | 1001 |
| 49 | 114 | 7 | 1001 |
| 50 | 115 | 7 | 1001 |
| 51 | 116 | 7 | 1001 |
| 52 | 117 | 7 | 8 |
| 53 | 118 | 7 | 8 |
| 54 | 119 | 7 | 8 |
| 55 | 120 | 7 | 8 |
| 56 | 121 | 7 | 8 |
| 57 | 122 | 7 | 8 |
| 58 | 123 | 7 | 8 |
| 59 | 124 | 7 | 8 |
| 60 | 125 | 7 | 8 |
| 61 | 126 | 7 | 8 |
| 62 | 127 | 7 | 8 |
| 63 | 128 | 7 | 8 |

## 4. Z2 other (whole baseline layer C4 groups remapped)

| old layer | baseline routes | new plane | new label | new z | new routes | direction old -> new |
|---|---:|---:|---|---:|---:|---|
| L8 | 48 | 9 | L9 | +0.10 | 48 | down -> down |
| L9 | 48 | 14 | L14 | +0.35 | 48 | down -> down |
| L14 | 48 | 15 | L15 | +0.40 | 48 | down -> down |
| L15 | 52 | 16 | L16 | +0.45 | 52 | down -> down |
| L16 | 52 | 17 | L17 | +0.55 | 52 | down -> up |
| L17 | 52 | 18 | L18 | +0.60 | 52 | up -> up |
| L18 | 52 | 19 | L19 | +0.65 | 52 | up -> up |
| L19 | 48 | 1002 | Z2_INTERFACE | +0.50 | 48 | up -> direct |

## 5. Direction changes

routes whose direction differs from the baseline: **200**

| change | routes |
|---|---:|
| down->direct | 52 |
| down->up | 100 |
| up->direct | 48 |

## 6. Direct routes (interface bodies)

* total direct routes: **100**
* Z1_INTERFACE (plane 1001): 52 routes
* Z2_INTERFACE (plane 1002): 48 routes

## 7. Heights and pitch

* baseline heights: 18
* new heights: **21**
* new minimum pitch: **0.050 mm** (required >= 0.05)

## 8. Summary

* assignment rows: 1024
* routes whose target plane changed vs baseline: 604
* routes whose target plane is unchanged: 420
* routes whose target z changed: 820
* manual groups unchanged (membership + plane ids): True

The baseline 18-layer experiment is read-only and was not modified; its assignment sha256 is recorded above.
