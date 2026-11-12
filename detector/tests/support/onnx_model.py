import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

# Mask coefficients per box, and the prototype masks' size for a 64-pixel input.
MASKS = 32
PROTOTYPES = 16


def write_detection_model(path, box=(10, 10, 40, 50), segment=False):
    """A real, tiny ONNX graph with Ultralytics' exported detection contract.

    Segmenting, the box's mask fills the box.
    """
    row = [*box, 0.9, 0, *([1.0] * MASKS if segment else [])]
    initializers = [
        numpy_helper.from_array(np.array([0], dtype=np.int64), "batch_index"),
        numpy_helper.from_array(np.array([1, len(row)], dtype=np.int64), "box_shape"),
        numpy_helper.from_array(np.array([[row]], dtype=np.float32), "box"),
    ]
    nodes = [
        helper.make_node("Shape", ["images"], ["input_shape"]),
        helper.make_node("Gather", ["input_shape", "batch_index"], ["batch"], axis=0),
        helper.make_node("Concat", ["batch", "box_shape"], ["output_shape"], axis=0),
        helper.make_node("Expand", ["box", "output_shape"], ["output0"]),
    ]
    outputs = [
        helper.make_tensor_value_info(
            "output0", TensorProto.FLOAT, ["batch", 1, len(row)]
        )
    ]
    if segment:
        shape = [1, MASKS, PROTOTYPES, PROTOTYPES]
        initializers += [
            numpy_helper.from_array(np.array(shape[1:], np.int64), "prototype_shape"),
            numpy_helper.from_array(np.ones(shape, np.float32), "prototypes"),
        ]
        nodes += [
            helper.make_node(
                "Concat", ["batch", "prototype_shape"], ["prototypes_shape"], axis=0
            ),
            helper.make_node("Expand", ["prototypes", "prototypes_shape"], ["output1"]),
        ]
        outputs.append(
            helper.make_tensor_value_info(
                "output1", TensorProto.FLOAT, ["batch", *shape[1:]]
            )
        )
    graph = helper.make_graph(
        nodes,
        "detector-contract",
        [
            helper.make_tensor_value_info(
                "images", TensorProto.FLOAT, ["batch", 3, "height", "width"]
            )
        ],
        outputs,
        initializer=initializers,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=9
    )
    helper.set_model_props(
        model,
        {
            "task": "segment" if segment else "detect",
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


def write_embedding_model(path, size=32, metadata=None):
    """A real, tiny embedding model: each picture's mean of every colour channel."""
    graph = helper.make_graph(
        [
            helper.make_node(
                "ReduceMean", ["images"], ["embeddings"], axes=[2, 3], keepdims=0
            )
        ],
        "embedding-contract",
        [
            helper.make_tensor_value_info(
                "images", TensorProto.FLOAT, ["batch", 3, size, size]
            )
        ],
        [helper.make_tensor_value_info("embeddings", TensorProto.FLOAT, ["batch", 3])],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=9
    )
    if metadata:
        helper.set_model_props(model, metadata)
    onnx.checker.check_model(model)
    onnx.save(model, path)
