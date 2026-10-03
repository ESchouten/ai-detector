"""Explicit aligned teacher-forcing CE, separate from the prior frozen buggy loss."""

import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as functional
from benchmark import digest, write_json
from transformers.loss import loss_utils
from transformers.models.vision_encoder_decoder import modeling_vision_encoder_decoder

ROOT = Path(__file__).parent


def aligned_loss(logits, labels):
    """Decoder inputs are already right-shifted; target position stays unchanged."""
    if logits.shape[:-1] != labels.shape:
        raise ValueError("Each decoder output position must have one aligned label")
    return functional.cross_entropy(
        logits.float().reshape(-1, logits.shape[-1]),
        labels.reshape(-1),
        ignore_index=-100,
    )


def freeze(path):
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr_loss.py",
        Path(loss_utils.__file__),
        Path(modeling_vision_encoder_decoder.__file__),
    ]
    write_json(
        path,
        {
            "scope": "Fixed CPU handcomputed teacher-forcing sanity check, no images/weights/training. Previous model results remain immutable.",
            "files": {str(p): digest(p) for p in paths},
            "labels": [[0, 3, 2, -100]],
            "decoder_start_token_id": 2,
            "pad_token_id": 1,
            "vocabulary": 4,
            "correct_logit": 10.0,
            "incorrect_logit": 0.0,
            "expected_decoder_inputs": [[2, 0, 3, 2]],
            "source": "https://github.com/huggingface/transformers/issues/40111",
            "expected": "Right-shift decoder inputs once; logits atpositiont target original labelt including BOS/EOS. Ignore padding. DefaultForCausalLMLoss instead shifts labels left, wrongly penalizing an aligned perfect prediction.",
        },
    )


def run(protocol, output):
    value = json.loads(protocol.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError("Loss proof source changed")
    labels = torch.tensor(value["labels"])
    decoder = modeling_vision_encoder_decoder.shift_tokens_right(labels, 1, 2)
    logits = torch.zeros(1, 4, 4, requires_grad=True)
    with torch.no_grad():
        for index, target in enumerate(labels[0]):
            if target >= 0:
                logits[0, index, target] = 10
    correct = aligned_loss(logits, labels)
    wrong = loss_utils.ForCausalLMLoss(logits=logits, labels=labels, vocab_size=4)
    fixed = loss_utils.ForCausalLMLoss(
        logits=logits, labels=labels, vocab_size=4, shift_labels=labels
    )
    correct.backward()
    result = {
        "protocol_sha256": digest(protocol),
        "decoder_inputs": decoder.tolist(),
        "aligned_cross_entropy": float(correct.detach()),
        "default_shifted_loss": float(wrong.detach()),
        "explicit_shift_labels_loss": float(fixed.detach()),
        "padded_position_gradient": logits.grad[0, -1].tolist(),
        "expected_near_zero": bool(correct < 0.001),
        "wrong_shift_material": bool(wrong > 9),
        "explicit_unshifted_targets_match": bool(torch.equal(correct, fixed)),
        "decoder_inputs_match": decoder.tolist() == value["expected_decoder_inputs"],
        "conclusion": "Installed default loss penalizes correct aligned teacher-forcing predictions because it shifts labels a second time. Explicit unshifted CE or supplying aligned shift_labels avoids this. No previous training score is overwritten.",
    }
    write_json(output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use new frozen output")
    if args.mode == "freeze":
        freeze(args.protocol)
    else:
        run(args.protocol, args.output)
