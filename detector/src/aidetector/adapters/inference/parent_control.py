"""Stop a short-lived helper process when its parent has gone away."""

import os
import sys
from time import sleep


def exit_with_parent() -> None:
    # The parent keeps this pipe open. A crash/forced shutdown must not leave
    # a model builder running after the monitoring process has gone away.
    # Blocking stdin reads can deadlock NumPy's native import on Windows:
    # https://github.com/numpy/numpy/issues/24290
    descriptor = sys.stdin.fileno()
    os.set_blocking(descriptor, False)
    while True:
        try:
            if not os.read(descriptor, 1):
                os._exit(1)
        except BlockingIOError:
            sleep(0.25)
