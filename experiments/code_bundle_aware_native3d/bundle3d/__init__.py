"""Bundle-aware Native 3D routing research package.

The package is additive: it reuses the frozen fslw / l3d / d56 / v3c4 geometry
and validation stack and never overwrites the previous campaign results.
"""
from .features import build_features  # noqa: F401
from .orbits import build_orbits  # noqa: F401
from .compatibility import build_graph  # noqa: F401
from .clustering import (graph_clustering, corridor_clustering,  # noqa: F401
                         kind_pure_clustering, evaluate_bundles)

__all__ = ['build_features', 'build_orbits', 'build_graph',
           'graph_clustering', 'corridor_clustering', 'kind_pure_clustering',
           'evaluate_bundles']
