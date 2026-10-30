# -*- coding: utf-8 -*-
"""C4-symmetric multilayer experiment package.

Strict four-fold rotation symmetry about the board centre (75, 75):

    R(x, y, z) = (150 - y, x, z)      # z is invariant

The 256 connection groups of ``connectivity_1024.json`` are exactly the C4
orbits (4 routes each, 1024 routes total); the frozen 2D base layout is already
exactly C4 symmetric (verified: max rotation deviation 4e-14 mm).

This package rebuilds the 3D solution so that every orbit uses **one**
representative ``(layer, a_in, a_out)`` and the other three members are built
with the rotation-mapped parameters (``(a_out, a_in)`` when the 90 deg rotation
reverses the traversal direction), which keeps the geometry exactly C4.
"""
