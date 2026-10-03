from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from aidetector.adapters.inference import MpsInferenceError

_MPS_LOCK = Lock()


@contextmanager
def mps_inference() -> Iterator[None]:
    """Serialize all model dispatch and result transfers on the shared Apple GPU."""
    # PyTorch's MPS command encoders are shared across models and are not safe
    # under concurrent dispatch: https://github.com/pytorch/pytorch/issues/197805
    import torch

    with _MPS_LOCK:
        try:
            yield
            torch.mps.synchronize()
        except torch.AcceleratorError as error:
            raise MpsInferenceError(
                "Apple GPU inference failed; a fresh detector process is required."
            ) from error
