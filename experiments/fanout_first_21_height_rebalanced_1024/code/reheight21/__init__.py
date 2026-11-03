# -*- coding: utf-8 -*-
"""20-height re-layered / interface-plane experiment package.

The 18-layer baseline (``FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024``) is frozen and
must stay readable/runnable.  This package adds the independent 21-routing-height
experiment ``FANOUT_FIRST_21_HEIGHT_REBALANCED_1024``:

* Z1 side compressed to a 50 um pitch (L2..L7, L20 at -0.05);
* one extra Z1 body plane L20 (id 20, physical z = -0.05 mm, NOT above L19);
* the two interface heights z=0 / z=0.5 participate in full 2D body routing
  (100 interface-direct routes, ``needs_transition=False``);
* Z2 manual U layers L10..L13 unchanged in id, z and membership;
* Z2 remaining adjacent routes shifted per the documented mapping;
* Z1 remaining opposite routes spread over five heights.

Modules
-------
model      : layer-plane model (21 routing heights), stack, paths, constants.
assign21   : new 1024-row assignment + audit + baseline diff.
run21      : experiment A-E driver + joint repair (Lead-owned).
validate21 : independent validator for the 21-height experiment.
plots21    : 21 per-height 2D images + comparison figures.
report21 / archive21 : comparison report + GitHub archive (no baseline overwrite).
"""
