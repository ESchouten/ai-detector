"""Write the coat check's two networks as the ONNX models ai-detector takes.

`keypoints.onnx` finds ALIKED keypoints in one picture: its input `image` is a
float32 RGB picture as 1×3×H×W in 0 to 1, scaled so its longer side is
`KeypointMatcher.size`; its outputs are `keypoints`, N×2 pixel positions (x, y),
and `descriptors`, N×128. `matcher.onnx` matches two pictures' keypoints with
LightGlue: inputs `keypoints0`, `descriptors0`, `size0` (width, height) and the
same for picture 1, each with a batch of 1; its output `scores` holds each of
picture 0's keypoints' match confidence, 0 where it has no mutual match. The
coat check counts the scores of at least `KeypointMatcher.confidence`.

Both follow kornia's networks with the settings `KeypointMatcher` uses: at most
512 keypoints above ALIKED's detection threshold, and LightGlue without early
stopping or point pruning. Only the keypoints' order differs, which LightGlue
does not depend on.
"""

from __future__ import annotations

from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from types import MethodType
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import torch


def _replicated(x: torch.Tensor, multiple: int) -> tuple[torch.Tensor, torch.Tensor]:
    """`x` padded by repeating its edges to a multiple of `multiple` on both
    sides, as ALIKED pads, with where the original starts; written with
    indices so the padding follows the picture's size in the exported model."""
    import torch

    shape = torch._shape_as_tensor(x)[2:]
    padding = (multiple - shape % multiple) % multiple
    start = padding // 2
    rows = (torch.arange(shape[0] + padding[0]) - start[0]).clamp(min=0)
    columns = (torch.arange(shape[1] + padding[1]) - start[1]).clamp(min=0)
    rows = torch.minimum(rows, shape[0] - 1)
    columns = torch.minimum(columns, shape[1] - 1)
    return x.index_select(2, rows).index_select(3, columns), start


def _dense_maps(
    aliked: torch.nn.Module, image: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """ALIKED's `extract_dense_map` with the padding worked out in the graph."""
    import torch
    import torch.nn.functional as F

    shape = torch._shape_as_tensor(image)[2:]
    padded, start = _replicated(image, 2**5)
    x1 = aliked.block1(padded)
    x2 = aliked.block2(aliked.pool2(x1))
    x3 = aliked.block3(aliked.pool4(x2))
    x4 = aliked.block4(aliked.pool4(x3))
    x1 = aliked.gate(aliked.conv1(x1))
    x2 = aliked.gate(aliked.conv2(x2))
    x3 = aliked.gate(aliked.conv3(x3))
    x4 = aliked.gate(aliked.conv4(x4))
    joined = torch.cat(
        [x1, aliked.upsample2(x2), aliked.upsample8(x3), aliked.upsample32(x4)], dim=1
    )
    score_map = torch.sigmoid(aliked.score_head(joined))
    feature_map = F.normalize(joined, p=2, dim=1)
    rows = torch.arange(shape[0]) + start[0]
    columns = torch.arange(shape[1]) + start[1]

    def unpadded(x: torch.Tensor) -> torch.Tensor:
        return x.index_select(2, rows).index_select(3, columns)

    return unpadded(feature_map), unpadded(score_map)


def _bilinear_sample(
    input: torch.Tensor,
    sample_h: torch.Tensor,
    sample_w: torch.Tensor,
    n_off_grps: int,
    c_per_off_grp: int,
) -> torch.Tensor:
    """kornia's `_bilinear_sample` for ALIKED's deformable convolutions,
    clamping to the input's size as a tensor: the exporter turns kornia's
    Python `max` into the example picture's size."""
    import torch

    size = torch._shape_as_tensor(input)
    height, width = size[2], size[3]
    h0, w0 = sample_h.floor(), sample_w.floor()
    lh, lw = (sample_h - h0).unsqueeze(2), (sample_w - w0).unsqueeze(2)
    h0, w0 = h0.long(), w0.long()
    flat = input.reshape(input.shape[0], n_off_grps, c_per_off_grp, -1)
    shape = (input.shape[0], n_off_grps, c_per_off_grp, *sample_h.shape[2:])

    def corner(hh: torch.Tensor, ww: torch.Tensor) -> torch.Tensor:
        valid = ((hh >= 0) & (hh < height) & (ww >= 0) & (ww < width)).to(input.dtype)
        hh = torch.minimum(hh.clamp(min=0), height - 1)
        ww = torch.minimum(ww.clamp(min=0), width - 1)
        index = (hh * width + ww).reshape(input.shape[0], n_off_grps, 1, -1)
        index = index.expand(-1, -1, c_per_off_grp, -1)
        return torch.gather(flat, 3, index).reshape(shape) * valid.unsqueeze(2)

    return (
        corner(h0, w0) * (1 - lh) * (1 - lw)
        + corner(h0, w0 + 1) * (1 - lh) * lw
        + corner(h0 + 1, w0) * lh * (1 - lw)
        + corner(h0 + 1, w0 + 1) * lh * lw
    )


def _deformable_forward(self, x: torch.Tensor) -> torch.Tensor:
    """kornia's `DeformableConv2d.forward` with the offset limit as a tensor."""
    import torch
    from kornia.feature.aliked.deform_conv2d import deform_conv2d

    size = torch._shape_as_tensor(x)
    limit = torch.maximum(size[2], size[3]).to(x.dtype) / 4.0
    offset = self.offset_conv(x)
    offset = torch.maximum(torch.minimum(offset, limit), -limit)
    return deform_conv2d(
        input=x,
        offset=offset,
        weight=self.regular_conv.weight,
        bias=self.regular_conv.bias,
        stride=self.stride,
        padding=self.padding,
        dilation=self.dilation,
    )


def _keypoints_network(keypoints: int) -> torch.nn.Module:
    import kornia.feature as features
    import torch
    import torch.nn.functional as F
    from kornia.feature.aliked.aliked import DeformableConv2d
    from kornia.geometry.subpix import nms2d

    aliked = features.ALIKED.from_pretrained(
        "aliked-n16", max_num_keypoints=keypoints, device=torch.device("cpu")
    ).eval()
    for module in aliked.modules():
        if isinstance(module, DeformableConv2d):
            if module.mask:
                raise ValueError("Only deformable convolutions without a mask")
            module.forward = MethodType(_deformable_forward, module)
    detector = aliked.dkd
    head = aliked.desc_head

    class Keypoints(torch.nn.Module):
        """ALIKED for one picture, with its keypoint selection written without
        branches on the picture's content, so the exporter can trace it."""

        def __init__(self) -> None:
            super().__init__()
            self.aliked = aliked

        def forward(self, image: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            feature_map, score_map = _dense_maps(self.aliked, image)
            shape = torch._shape_as_tensor(score_map)
            h, w = shape[2], shape[3]
            radius = detector.radius
            nms = nms2d(score_map, (detector.kernel_size, detector.kernel_size))
            rows = torch.arange(h, device=image.device)
            columns = torch.arange(w, device=image.device)
            inside = ((rows >= radius) & (rows < h - radius))[:, None] & (
                (columns >= radius) & (columns < w - radius)
            )[None, :]
            nms = (nms * inside).reshape(-1)
            scores = score_map.reshape(-1)
            # Above the detection threshold, or above the mean when nothing is.
            above = nms > detector.scores_th
            threshold = torch.where(
                above.any(),
                torch.full_like(scores[0], detector.scores_th),
                scores.mean(),
            )
            candidates = torch.where(
                nms > threshold, scores, torch.full_like(scores, -1)
            )
            best = torch.topk(candidates, detector.n_limit)
            indices = best.indices[best.values > -1]

            # Soft-argmax refinement within each keypoint's window, as DKD does.
            patches = detector.unfold(score_map)[0].t()[indices]
            nearest = torch.stack(
                [indices % w, torch.div(indices, w, rounding_mode="trunc")], dim=1
            ).to(score_map.dtype)
            top = patches.max(dim=1).values[:, None]
            weights = ((patches - top) / detector.temperature).exp()
            residual = weights @ detector.hw_grid / weights.sum(dim=1, keepdim=True)
            size = torch.stack([w - 1, h - 1]).to(score_map.dtype)
            normalised = (nearest + residual) / size * 2 - 1

            # The descriptor head, as SDDH does it for one picture.
            features_map = feature_map[0]
            channels = features_map.shape[0]
            pixels = (normalised / 2 + 0.5) * size
            window = head.kernel_size
            corner = (pixels.long() - window / 2 + 1).long()
            corner = torch.stack(
                [
                    torch.minimum(corner[:, 0].clamp(min=0), w - 1 - window),
                    torch.minimum(corner[:, 1].clamp(min=0), h - 1 - window),
                ],
                dim=1,
            )
            offsets = torch.arange(window, device=image.device)
            dx, dy = torch.meshgrid(offsets, offsets, indexing="xy")
            xs = corner[:, None, None, 0] + dx[None]
            ys = corner[:, None, None, 1] + dy[None]
            patch = features_map[:, ys, xs].permute(1, 0, 2, 3)
            count = patch.shape[0]
            limit = torch.maximum(h, w).to(score_map.dtype) / 4.0
            offset = torch.maximum(
                torch.minimum(head.offset_conv(patch), limit), -limit
            )
            offset = offset[:, :, 0, 0].view(count, 2, head.n_pos).permute(0, 2, 1)
            position = 2.0 * (pixels[:, None] + offset) / size - 1
            sampled = F.grid_sample(
                features_map[None],
                position.reshape(1, count * head.n_pos, 1, 2),
                mode="bilinear",
                align_corners=True,
            )
            sampled = sampled.reshape(channels, count, head.n_pos, 1).permute(
                1, 0, 2, 3
            )
            sampled = torch.selu(head.sf_conv(sampled)).squeeze(-1)
            descriptors = torch.einsum("ncp,pcd->nd", sampled, head.agg_weights)
            descriptors = F.normalize(descriptors, p=2.0, dim=1)
            # Pixel positions in the picture, as kornia's ALIKED returns them.
            return size * (normalised + 1) / 2, descriptors

    return Keypoints().eval()


# kornia's LightGlue blocks, with each reshape spelled out: the exporter loses
# the rank of `unflatten` with a -1 and then cannot transpose.


def _split(x: torch.Tensor, heads: int, parts: int = 1) -> torch.Tensor:
    """1 × N × (heads·width·parts) to 1 × heads × N × width (× parts)."""
    width = x.shape[-1] // heads // parts
    if parts == 1:
        return x.reshape(1, -1, heads, width).transpose(1, 2)
    return x.reshape(1, -1, heads, width, parts).transpose(1, 2)


def _joined(x: torch.Tensor) -> torch.Tensor:
    return x.transpose(1, 2).reshape(1, -1, x.shape[1] * x.shape[-1])


def _rotated(x: torch.Tensor, encoding: torch.Tensor) -> torch.Tensor:
    import torch

    heads, width = x.shape[1], x.shape[-1]
    pairs = x.reshape(1, heads, -1, width // 2, 2)
    half = torch.stack((-pairs[..., 1], pairs[..., 0]), dim=-1)
    return x * encoding[0] + half.reshape(1, heads, -1, width) * encoding[1]


def _own(block: torch.nn.Module, x: torch.Tensor, encoding: torch.Tensor):
    import torch
    import torch.nn.functional as F

    qkv = _split(block.Wqkv(x), block.num_heads, 3)
    q = _rotated(qkv[..., 0], encoding)
    k = _rotated(qkv[..., 1], encoding)
    context = F.scaled_dot_product_attention(q, k, qkv[..., 2])
    message = block.out_proj(_joined(context))
    return x + block.ffn(torch.cat([x, message], -1))


def _across(block: torch.nn.Module, x0: torch.Tensor, x1: torch.Tensor):
    import torch
    import torch.nn.functional as F

    qk0 = _split(block.to_qk(x0), block.heads) * block.scale**0.5
    qk1 = _split(block.to_qk(x1), block.heads) * block.scale**0.5
    v0, v1 = _split(block.to_v(x0), block.heads), _split(block.to_v(x1), block.heads)
    similarity = qk0 @ qk1.transpose(-2, -1)
    m0 = block.to_out(_joined(F.softmax(similarity, dim=-1) @ v1))
    m1 = block.to_out(_joined(F.softmax(similarity.transpose(-2, -1), dim=-1) @ v0))
    return (
        x0 + block.ffn(torch.cat([x0, m0], -1)),
        x1 + block.ffn(torch.cat([x1, m1], -1)),
    )


def _encoded(encoding: torch.nn.Module, points: torch.Tensor) -> torch.Tensor:
    import torch

    projected = encoding.Wr(points)
    both = torch.stack([torch.cos(projected), torch.sin(projected)], 0)
    # Each frequency twice in a row, as `repeat_interleave(2, dim=-1)`.
    return torch.stack([both, both], -1).reshape(2, 1, 1, -1, 2 * projected.shape[-1])


def _matcher_network() -> torch.nn.Module:
    import kornia.feature as features
    import torch
    from kornia.feature.lightglue import filter_matches, normalize_keypoints

    glue = features.LightGlue(
        "aliked", depth_confidence=-1, width_confidence=-1, flash=False
    ).eval()

    class Matcher(torch.nn.Module):
        """LightGlue for one pair, every layer and every keypoint."""

        def __init__(self) -> None:
            super().__init__()
            self.glue = glue

        def forward(
            self,
            keypoints0: torch.Tensor,
            descriptors0: torch.Tensor,
            size0: torch.Tensor,
            keypoints1: torch.Tensor,
            descriptors1: torch.Tensor,
            size1: torch.Tensor,
        ) -> torch.Tensor:
            encoding0 = _encoded(glue.posenc, normalize_keypoints(keypoints0, size0))
            encoding1 = _encoded(glue.posenc, normalize_keypoints(keypoints1, size1))
            desc0 = glue.input_proj(descriptors0)
            desc1 = glue.input_proj(descriptors1)
            for layer in glue.transformers:
                desc0 = _own(layer.self_attn, desc0, encoding0)
                desc1 = _own(layer.self_attn, desc1, encoding1)
                desc0, desc1 = _across(layer.cross_attn, desc0, desc1)
            assignment, _ = glue.log_assignment[-1](desc0, desc1)
            _, _, scores, _ = filter_matches(assignment, glue.conf.filter_threshold)
            return scores

    return Matcher().eval()


@contextmanager
def _traceable_sampling():
    # The package exports a function of the module's own name.
    module = import_module("kornia.feature.aliked.deform_conv2d")
    original = module._bilinear_sample
    module._bilinear_sample = _bilinear_sample
    try:
        yield
    finally:
        module._bilinear_sample = original


def export_coat_check(
    out: Path, pictures: list[Path], size: int = 512, keypoints: int = 512
) -> dict[str, float]:
    """Export both networks into the folder `out`, then match `pictures` in
    pairs with ONNX Runtime and with kornia, and return the largest difference
    in keypoints and in matches at the confidence `KeypointMatcher` uses."""
    import onnx
    import torch

    from reid.local import KeypointMatcher

    out.mkdir(parents=True, exist_ok=True)
    finder = _keypoints_network(keypoints)
    matcher = _matcher_network()
    example = torch.rand(
        1, 3, size * 3 // 4, size, generator=torch.Generator().manual_seed(0)
    )
    with torch.no_grad(), _traceable_sampling():
        points, descriptors = finder(example)
        torch.onnx.export(
            finder,
            (example,),
            str(out / "keypoints.onnx"),
            input_names=["image"],
            output_names=["keypoints", "descriptors"],
            dynamic_axes={
                "image": {2: "height", 3: "width"},
                "keypoints": {0: "found"},
                "descriptors": {0: "found"},
            },
            opset_version=18,
            dynamo=False,
        )
        sizes = torch.tensor(
            [[example.shape[-1], example.shape[-2]]], dtype=torch.float32
        )
        torch.onnx.export(
            matcher,
            (
                points[None],
                descriptors[None],
                sizes,
                points[None],
                descriptors[None],
                sizes,
            ),
            str(out / "matcher.onnx"),
            input_names=[
                "keypoints0",
                "descriptors0",
                "size0",
                "keypoints1",
                "descriptors1",
                "size1",
            ],
            output_names=["scores"],
            dynamic_axes={
                "keypoints0": {1: "found0"},
                "descriptors0": {1: "found0"},
                "keypoints1": {1: "found1"},
                "descriptors1": {1: "found1"},
                "scores": {1: "found0"},
            },
            opset_version=18,
            dynamo=False,
        )
    for name, description in (
        ("keypoints", f"ALIKED aliked-n16, at most {keypoints} keypoints, {size} px"),
        ("matcher", "LightGlue for ALIKED, v0.1_arxiv weights"),
    ):
        graph = onnx.load(str(out / f"{name}.onnx"))
        onnx.helper.set_model_props(
            graph, {"description": description, "size": str(size)}
        )
        onnx.checker.check_model(graph)
        onnx.save(graph, str(out / f"{name}.onnx"))
    return _compare(out, pictures, KeypointMatcher(size, keypoints, device="cpu"))


def _compare(out: Path, pictures: list[Path], reference) -> dict[str, float]:
    import onnxruntime as ort
    from PIL import Image

    providers = ["CPUExecutionProvider"]
    finder = ort.InferenceSession(str(out / "keypoints.onnx"), providers=providers)
    matcher = ort.InferenceSession(str(out / "matcher.onnx"), providers=providers)
    found = {}
    keypoint_difference = 0.0
    for path in pictures:
        with Image.open(path) as picture:
            picture = picture.convert("RGB")
            scale = reference.size / max(picture.size)
            picture = picture.resize(
                (
                    max(32, round(picture.width * scale)),
                    max(32, round(picture.height * scale)),
                ),
                Image.Resampling.BILINEAR,
            )
        pixels = np.asarray(picture, dtype=np.float32) / 255.0
        points, descriptors = finder.run(
            None, {"image": pixels.transpose(2, 0, 1)[None]}
        )
        expected = reference._describe(path)[0].cpu().numpy()
        if len(points) != len(expected):
            keypoint_difference = float("inf")
        else:
            order = np.lexsort(points.T)
            keypoint_difference = max(
                keypoint_difference,
                float(np.abs(points[order] - expected[np.lexsort(expected.T)]).max()),
            )
        found[path] = (
            points,
            descriptors,
            np.array([[picture.width, picture.height]], np.float32),
        )
    pairs = [(a, b) for a, b in zip(pictures, pictures[1:], strict=False)]
    expected = reference.matches(pairs)
    match_difference = 0.0
    for (a, b), count in zip(pairs, expected, strict=True):
        scores = matcher.run(
            None,
            {
                "keypoints0": found[a][0][None],
                "descriptors0": found[a][1][None],
                "size0": found[a][2],
                "keypoints1": found[b][0][None],
                "descriptors1": found[b][1][None],
                "size1": found[b][2],
            },
        )[0]
        produced = float((scores >= reference.confidence).sum())
        match_difference = max(match_difference, abs(produced - float(count)))
    return {"keypoints": keypoint_difference, "matches": match_difference}
