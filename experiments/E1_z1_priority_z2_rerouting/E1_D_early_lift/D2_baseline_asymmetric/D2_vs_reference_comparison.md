# D2 refinement: exact deltas vs reference layout

| metric | reference | this experiment | delta | delta % |
|---|---:|---:|---:|---:|
| routed | 1024 | 1024 | 0.0 | 0.0 |
| unique_crossing_pairs | 6078 | 4670 | -1408.0 | -23.166 |
| z1_crossing_pairs | 5256 | 3400 | -1856.0 | -35.312 |
| z2_crossing_pairs | 752 | 752 | 0.0 | 0.0 |
| high_layer_crossing_pairs | 70 | 518 | 448.0 | 640.0 |
| adjacent_related_events | 3680 | 2336 | -1344.0 | -36.522 |
| adjacent_related_pairs | 3680 | 2336 | -1344.0 | -36.522 |
| adjacent_line_events | 2276 | 932 | -1344.0 | -59.051 |
| adjacent_arc_events | 1404 | 1404 | 0.0 | 0.0 |
| opposite_opposite_events | 1064 | 1064 | 0.0 | 0.0 |
| z1_hv_same_height_pairs | 1092 | 1092 | 0.0 | 0.0 |
| transitions | 940 | 940 | 0.0 | 0.0 |
| total_length_mm | 97205.1808 | 97205.1808 | 0.0 | 0.0 |
| fabrication_hours | 27.0014 | 27.0014 | 0.0 | 0.0 |
| l6_routes | 0 | 0 | 0.0 | None |
| l7_routes | 0 | 0 | 0.0 | None |
| violations | 0 | 0 | 0.0 | None |
| validation_status | exploratory_only | exploratory_only | None | None |

Refined `a_in`/`a_out` windows of 32 of 206 movable Z1-opposite routes (independent per pair member, world-legal only).
