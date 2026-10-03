"""Exact split of the reviewed MIEWid network; no new encoder architecture."""

import torch

TAIL_PREFIXES = (
    "backbone.blocks.5.22.",
    "backbone.blocks.5.23.",
    "backbone.conv_head.",
)


def split_model(model):
    stages = model.backbone.blocks
    if len(stages) != 6 or len(stages[-1]) != 24:
        raise ValueError("Pinned EfficientNet block structure changed")
    prefix = torch.nn.Sequential(
        model.backbone.conv_stem,
        model.backbone.bn1,
        *stages[:-1],
        *stages[-1][:-2],
    )
    tail = torch.nn.Sequential(
        *stages[-1][-2:],
        model.backbone.conv_head,
        model.backbone.bn2,
        model.backbone.global_pool,
        torch.nn.Flatten(1),
        model.bn,
    )
    return prefix, tail


def freeze_normalization(module):
    for layer in module.modules():
        if isinstance(layer, torch.nn.modules.batchnorm._BatchNorm):
            layer.eval()
            layer.requires_grad_(False)


def trainable_tail(model):
    model.eval().requires_grad_(False)
    prefix, tail = split_model(model)
    for name, parameter in model.named_parameters():
        if name.startswith(TAIL_PREFIXES):
            parameter.requires_grad_(True)
    freeze_normalization(model)
    prefix.eval()
    # Evaluation mode freezes normalization and stochastic depth; gradients still flow.
    tail.eval()
    freeze_normalization(tail)
    names = [
        name for name, parameter in model.named_parameters() if parameter.requires_grad
    ]
    if not names or any(not name.startswith(TAIL_PREFIXES) for name in names):
        raise ValueError("Only the frozen exact tail parameter set may train")
    return prefix, tail, names


def normalized_tail(tail, maps):
    return torch.nn.functional.normalize(tail(maps), dim=1)


def contrastive_loss(encoded, base, count):
    """Same-frame anchors only; partner crops are positives, never negatives."""
    anchors, positives = encoded[:count], encoded[count:]
    positive = (anchors * positives).sum(dim=1, keepdim=True)
    negative = anchors @ anchors.T
    negative = negative.masked_fill(
        torch.eye(count, dtype=torch.bool, device=encoded.device), -1e9
    )
    logits = torch.cat((positive, negative), dim=1) / 0.1
    contrastive = torch.nn.functional.cross_entropy(
        logits, torch.zeros(count, dtype=torch.long, device=encoded.device)
    )
    preservation = (1 - (base * encoded).sum(dim=1)).mean()
    return contrastive + preservation


def validate_training_rows(rows):
    if len(rows) < 4 or len(rows) > 8 or len(rows) % 2:
        raise ValueError("Batch is two to four anchors and their positive partners")
    count = len(rows) // 2
    anchors, positives = rows[:count], rows[count:]
    if (
        len({r["second"] for r in anchors}) != 1
        or len({r["track_id"] for r in anchors}) != count
    ):
        raise ValueError("Negatives must be distinct objects in the same frame")
    for a, p in zip(anchors, positives, strict=True):
        if any(
            r["kind"] != "observation"
            or r["track_id"] not in range(6)
            or not 0 <= r["second"] <= 419
            for r in (a, p)
        ):
            raise ValueError("Unknown or non-training data entered optimization")
        if (
            a["track_id"] != p["track_id"]
            or not 10 <= abs(a["second"] - p["second"]) <= 30
        ):
            raise ValueError("Temporal positive identity or gap changed")
