"""Research-only narrow imports; selected upstream implementations stay unchanged."""

import importlib
import sys
import types
from pathlib import Path


def load_reference():
    # This isolated reference has no Transformers training dependency.
    sys.modules["transformers"] = None
    ROOT = Path("/tmp/autocattlogger-feasibility/dependencies/mmpose")

    def namespace(name):
        m = types.ModuleType(name)
        m.__path__ = [str(ROOT.joinpath(*name.split(".")))]
        sys.modules[name] = m
        return m

    def load(name):
        return importlib.import_module(name)

    for name in [
        "mmpose",
        "mmpose.models",
        "mmpose.models.backbones",
        "mmpose.models.heads",
        "mmpose.models.heads.heatmap_heads",
        "mmpose.models.utils",
        "mmpose.models.losses",
        "mmpose.utils",
        "mmpose.structures",
        "mmpose.structures.bbox",
        "mmpose.evaluation",
        "mmpose.evaluation.functional",
        "mmpose.codecs",
        "mmpose.codecs.utils",
        "mmpose.datasets",
        "mmpose.datasets.transforms",
    ]:
        namespace(name)
    load("mmpose.registry")
    structures = sys.modules["mmpose.structures"]
    structures.MultilevelPixelData = load(
        "mmpose.structures.multilevel_pixel_data"
    ).MultilevelPixelData
    structures.PoseDataSample = load(
        "mmpose.structures.pose_data_sample"
    ).PoseDataSample
    utils = sys.modules["mmpose.codecs.utils"]
    for file, names in [
        ("gaussian_heatmap", ["generate_udp_gaussian_heatmaps"]),
        ("offset_heatmap", ["generate_offset_heatmap"]),
        ("post_processing", ["get_heatmap_maximum", "get_simcc_maximum"]),
        ("refinement", ["refine_keypoints_dark_udp"]),
    ]:
        m = load("mmpose.codecs.utils." + file)
        for name in names:
            setattr(utils, name, getattr(m, name))
    functional = sys.modules["mmpose.evaluation.functional"]
    functional.pose_pck_accuracy = load(
        "mmpose.evaluation.functional.keypoint_eval"
    ).pose_pck_accuracy
    bbox = sys.modules["mmpose.structures.bbox"]
    for name in ["get_udp_warp_matrix", "get_warp_matrix"]:
        setattr(bbox, name, getattr(load("mmpose.structures.bbox.transforms"), name))
    HRNet = load("mmpose.models.backbones.hrnet").HRNet
    HeatmapHead = load("mmpose.models.heads.heatmap_heads.heatmap_head").HeatmapHead
    KeypointMSELoss = load("mmpose.models.losses.heatmap_loss").KeypointMSELoss
    UDPHeatmap = load("mmpose.codecs.udp_heatmap").UDPHeatmap
    TopdownAffine = load("mmpose.datasets.transforms.topdown_transforms").TopdownAffine
    flip_heatmaps = load("mmpose.models.utils.tta").flip_heatmaps
    return types.SimpleNamespace(
        HRNet=HRNet,
        HeatmapHead=HeatmapHead,
        KeypointMSELoss=KeypointMSELoss,
        UDPHeatmap=UDPHeatmap,
        TopdownAffine=TopdownAffine,
        flip_heatmaps=flip_heatmaps,
        bbox_transforms=load("mmpose.structures.bbox.transforms"),
    )
