"""Model assets, execution-provider lifetime, and YOLO inference."""


class MpsInferenceError(RuntimeError):
    """Apple GPU inference failed and requires a fresh detector process."""
