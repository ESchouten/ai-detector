"""Corrected public forward contract must never invoke the erroneous label loss."""

import torch
from eartag_trocr_cpu import forward_loss


def test_shift_inputs_once_and_never_pass_labels_to_forward():
    labels = torch.tensor([[0, 3, 2, -100]])
    image = torch.zeros(1, 3, 2, 2)

    class Model:
        def prepare_decoder_input_ids_from_labels(self, actual):
            assert torch.equal(actual, labels)
            return torch.tensor([[2, 0, 3, 2]])

        def __call__(self, *, pixel_values, decoder_input_ids):
            assert pixel_values is image
            assert decoder_input_ids.tolist() == [[2, 0, 3, 2]]
            return type(
                "Output",
                (),
                {
                    "logits": torch.tensor(
                        [
                            [
                                [10.0, 0, 0, 0],
                                [0, 0, 0, 10.0],
                                [0, 0, 10.0, 0],
                                [100.0, 0, 0, 0],
                            ]
                        ]
                    )
                },
            )()

    assert forward_loss(Model(), image, labels) < 0.001
