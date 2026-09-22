import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


def write_detection_model(path):
    """A real, tiny ONNX graph with Ultralytics' exported detection contract."""
    initializers = [
        numpy_helper.from_array(np.array([0], dtype=np.int64), "batch_index"),
        numpy_helper.from_array(np.array([1, 6], dtype=np.int64), "box_shape"),
        numpy_helper.from_array(
            np.array([[[10, 10, 40, 50, 0.9, 0]]], dtype=np.float32), "box"
        ),
    ]
    nodes = [
        helper.make_node("Shape", ["images"], ["input_shape"]),
        helper.make_node("Gather", ["input_shape", "batch_index"], ["batch"], axis=0),
        helper.make_node("Concat", ["batch", "box_shape"], ["output_shape"], axis=0),
        helper.make_node("Expand", ["box", "output_shape"], ["output0"]),
    ]
    graph = helper.make_graph(
        nodes,
        "detector-contract",
        [
            helper.make_tensor_value_info(
                "images", TensorProto.FLOAT, ["batch", 3, "height", "width"]
            )
        ],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, ["batch", 1, 6])],
        initializer=initializers,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=9
    )
    helper.set_model_props(
        model,
        {
            "task": "detect",
            "stride": "32",
            "batch": "2",
            "imgsz": "[64, 64]",
            "names": "{0: 'cow'}",
            "end2end": "True",
            "args": "{'dynamic': True}",
        },
    )
    onnx.checker.check_model(model)
    onnx.save(model, path)
