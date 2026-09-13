"""
SolidWorks Automation Package
-----------------------------
Complete automation class combining all operations.
"""

from .base import SolidWorksAutomation as _BaseAutomation
from .documents import DocumentOperations
from .sketches import SketchOperations
from .features import FeatureOperations
from .advanced_features_sw2026 import AdvancedFeatureOperations
from .more_features import MoreFeatureOperations
from .bodies import BodyOperations
from .body_identity import register_identity_tools
from .body_identity_resilient import BodyIdentityOperations
from .cut_direction import CutDirectionOperations, register_cut_direction_tools
from .geometry_probe import GeometryProbeOperations
from .view import ViewOperations
from .transactions_semantic import TransactionOperations
from .dimension_update import DimensionUpdateOperations
from .parametric_sw2026 import ParametricSketchOperations
from .vectorization import ImageSketchOperations
from .high_level import HighLevelOperations


# server.py imports automation before tool_registry. Register semantic identity
# first, then extend semantic_cut with the deterministic direction preflight and
# expose the read-only resolver without duplicating the legacy dispatch table.
register_identity_tools()
register_cut_direction_tools()


# MoreFeatureOperations precedes FeatureOperations so its improved
# fillet_edges/chamfer_edges (ray edge selection) win over the legacy ones.
# CutDirectionOperations precedes BodyIdentityOperations so its semantic_cut
# wrapper can perform the read-only direction preflight and then delegate to the
# existing resilient semantic identity implementation through cooperative MRO.
class SolidWorksAutomation(_BaseAutomation, DocumentOperations,
                           TransactionOperations, DimensionUpdateOperations,
                           ParametricSketchOperations, ImageSketchOperations,
                           HighLevelOperations, SketchOperations,
                           MoreFeatureOperations, FeatureOperations,
                           AdvancedFeatureOperations, CutDirectionOperations,
                           BodyIdentityOperations, BodyOperations,
                           GeometryProbeOperations, ViewOperations):
    """
    Complete SolidWorks automation class

    Combines all operation mixins:
    - Base: Connection, document access, freeze-bar protection, utilities
    - Documents: Create, open, save, close documents
    - Sketches: Create sketches, draw 2D geometry
    - Features: Extrude, cut, fillet, chamfer, list
    - AdvancedFeatures: delete/rename/status, advanced_extrude/advanced_cut
    - CutDirection: read-only sketch/body direction preflight for semantic cuts
    - BodyIdentity: durable body:<id> resolution and semantic_extrude/cut
    - Bodies: list/show/hide/rename/transparency
    - GeometryProbe: probe_ray(s), select_face_by_ray, sketch_contour
    - View: take_screenshot, set_view_orientation

    Example:
        sw = SolidWorksAutomation()
        sw.connect()
        sw.create_new_part()
        sw.create_sketch("Front")
        sw.draw_circle(0, 0, 25)
        sw.extrude_sketch(10)
        sw.save_document("C:/Parts/MyPart.sldprt")
    """
    pass


__all__ = [
    "SolidWorksAutomation",
    "DocumentOperations",
    "SketchOperations",
    "FeatureOperations",
    "AdvancedFeatureOperations",
    "CutDirectionOperations",
    "BodyIdentityOperations",
    "MoreFeatureOperations",
    "BodyOperations",
    "GeometryProbeOperations",
    "ViewOperations",
    "TransactionOperations",
    "DimensionUpdateOperations",
    "ParametricSketchOperations",
    "ImageSketchOperations",
    "HighLevelOperations",
]
