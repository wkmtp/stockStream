"""Generate placeholder ONNX model files for development/testing.

These are valid ONNX files that will load without errors,
but produce random output — they are NOT real AI models.
Use download_models.py to get real models.

Usage:
    python scripts/generate_placeholder_models.py
"""

# pyright: reportUnknownMemberType=false, reportExplicitAny=false, reportAny=false

import sys
from pathlib import Path
from typing import Any

import numpy as np
import onnx
from onnx import TensorProto, helper


def make_const(name: str, value: Any) -> Any:  # np.ndarray
    """Create a Constant node that outputs a fixed tensor."""
    t = helper.make_tensor(name, TensorProto.FLOAT, value.shape, value.flatten())
    return onnx.helper.make_node("Constant", [], [name], value=t)


def create_face_detector_onnx(output_path: Path) -> None:
    """Create a valid SCRFD-style face detector ONNX.

    Input:  (B, 3, 640, 640) float32 RGB image
    Outputs:
        - scores  (N,)    float32  — confidence scores
        - bboxes  (N, 4) float32  — [x1, y1, x2, y2] normalized
        - kps     (N, 10) float32  — 5 landmarks (x, y pairs)
    """
    # Constants must appear as ONNX nodes BEFORE they are used (topological order)
    c_score  = make_const("c_score",  np.array([0.95],     np.float32))
    c_bbox   = make_const("c_bbox",   np.array([[0.2, 0.2, 0.8, 0.8]], np.float32))
    c_kps    = make_const("c_kps",    np.array([[0.3, 0.3, 0.7, 0.3,
                                                  0.3, 0.7, 0.7, 0.3, 0.5, 0.5]], np.float32))

    # Identity from input (keeps shape valid for tracing)
    id_node  = onnx.helper.make_node("Identity", ["input"], ["preprocessed"])

    # ReLU to clamp values to valid range
    relu_node = onnx.helper.make_node("Relu", ["preprocessed"], ["preprocessed_relu"])

    # Outputs are Identity of constants — topological: const → identity → output
    scores_node = onnx.helper.make_node("Identity", ["c_score"],  ["scores"])
    bboxes_node = onnx.helper.make_node("Identity", ["c_bbox"],   ["bboxes"])
    kps_node    = onnx.helper.make_node("Identity", ["c_kps"],    ["kps"])

    input_tensor  = helper.make_tensor_value_info("input",  TensorProto.FLOAT, [1, 3, 640, 640])
    scores_tensor = helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1])
    bboxes_tensor = helper.make_tensor_value_info("bboxes", TensorProto.FLOAT, [1, 4])
    kps_tensor    = helper.make_tensor_value_info("kps",    TensorProto.FLOAT, [1, 10])

    graph = onnx.helper.make_graph(
        nodes=[c_score, c_bbox, c_kps, id_node, relu_node,
               scores_node, bboxes_node, kps_node],
        name="face_detector_placeholder",
        inputs=[input_tensor],
        outputs=[scores_tensor, bboxes_tensor, kps_tensor],
        initializer=[],
    )

    model = onnx.helper.make_model(graph, opset_imports=[onnx.helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(output_path))
    size = output_path.stat().st_size
    print(f"[OK]   Created: {output_path} ({size // 1024} KB)")


def create_wav2lip_onnx(output_path: Path) -> None:
    """Create a valid Wav2Lip GAN ONNX placeholder.

    Input:
        face_sequences: (B, 5, 6, 96, 96) float32
        mel_sequences:  (B, 5, 80, 16)  float32

    Output:
        face_out: (B, 3, 96, 96) float32  — lip-synced face
    """
    input_face = helper.make_tensor_value_info(
        "face_sequences", TensorProto.FLOAT, [1, 5, 6, 96, 96]
    )
    input_mel = helper.make_tensor_value_info(
        "mel_sequences", TensorProto.FLOAT, [1, 5, 80, 16]
    )
    output_face = helper.make_tensor_value_info(
        "face_out", TensorProto.FLOAT, [1, 3, 96, 96]
    )

    # Constants must come before any nodes that use them
    _c_face_pool = make_const("c_face_pool",
                             np.zeros((1, 5, 1, 96, 96), np.float32))
    c_face_rgb  = make_const("c_face_rgb",
                             np.zeros((1, 3, 96, 96), np.float32))

    # Simple: just use identity + relu on the first 3 channels of face
    # mel is ignored in placeholder (would do attention in real model)
    relu_node   = onnx.helper.make_node("Relu",    ["c_face_rgb"], ["face_relu"])
    clip_node   = onnx.helper.make_node("Clip",     ["face_relu", "c_zero", "c_one"], ["face_out"])
    # constants used above
    c_zero = make_const("c_zero", np.array([0.0], np.float32))
    c_one  = make_const("c_one",  np.array([1.0], np.float32))

    graph = onnx.helper.make_graph(
        nodes=[c_face_rgb, c_zero, c_one, relu_node, clip_node],
        name="wav2lip_gan_placeholder",
        inputs=[input_face, input_mel],
        outputs=[output_face],
    )

    model = onnx.helper.make_model(graph, opset_imports=[onnx.helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(output_path))
    size = output_path.stat().st_size
    print(f"[OK]   Created: {output_path} ({size // 1024} KB)")


def main() -> int:
    base_dir = Path(__file__).parent.parent.resolve()
    models_dir = base_dir / "models"
    models_dir.mkdir(exist_ok=True)

    print("Generating placeholder ONNX models...")
    print(f"  Output: {models_dir}")
    print()

    # Face detector
    create_face_detector_onnx(models_dir / "face_detector.onnx")

    # Wav2Lip
    create_wav2lip_onnx(models_dir / "wav2lip_gan.onnx")

    # TTS: create a minimal onnx with proper structure
    # (Real model must be downloaded separately)
    tts_path = models_dir / "zh_CN-huayan-medium.onnx"
    if not tts_path.exists():
        print(f"[INFO]  Piper TTS model not in models/ — run download_models.py")
        print(f"        Expected: {tts_path}")
    else:
        print(f"[OK]   Piper TTS: {tts_path} ({tts_path.stat().st_size // (1024*1024)} MB)")

    print()
    print("NOTE: Placeholder models are for DEV/TEST only.")
    print("      Run: python scripts/download_models.py --all")
    print("      to get real models.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
