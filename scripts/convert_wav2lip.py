"""Convert Wav2Lip GAN PyTorch checkpoint to ONNX.

Prerequisites:
    pip install torch torchvision numpy onnx

Manual steps:
    1. Download wav2lip_gan.pth from:
       https://github.com/Rudrabha/Wav2Lip/releases/download/v1.2/wav2lip_gan.pth

    2. Place wav2lip_gan.pth in models/wav2lip_gan.pth

    3. Run: python scripts/convert_wav2lip.py

Output: models/wav2lip_gan.onnx
"""

# pyright: reportMissingParameterType=false, reportUnknownParameterType=false
# pyright: reportUnannotatedClassAttribute=false, reportImplicitOverride=false, reportAny=false
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812


class Conv(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
                 padding=None, bias=False, activation=""):
        super().__init__()
        if padding is None:
            padding = kernel_size // 2
        self.conv = nn.Conv3d(in_channels, out_channels, kernel_size,
                              stride=stride, padding=padding, bias=bias)
        self.activation = activation

    def forward(self, x):
        out = self.conv(x)
        if self.activation == "relu":
            return F.relu(out)
        elif self.activation == "lrelu":
            return F.leaky_relu(out, 0.1)
        elif self.activation == "tanh":
            return torch.tanh(out)
        return out


class ResBlock5d(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = Conv(channels, channels, kernel_size=3, activation="relu")
        self.conv2 = Conv(channels, channels, kernel_size=3)

    def forward(self, x):
        return x + 0.3 * self.conv2(self.conv1(x))


class Wav2Lip(nn.Module):
    """Wav2Lip Generator — matches the original Wav2Lip-GAN architecture.

    Input:
        face_sequences: (B, 5, 6, 96, 96) — 5 consecutive face crops, 6 channels
        mel_sequences:  (B, 5, 80, 16)  — 5 mel frames, 80 bins, 16 time steps

    Output:
        face_out: (B, 3, 96, 96) — lip-synced face RGB
    """

    def __init__(self):
        super().__init__()
        self.face_conv1 = Conv(6, 32, kernel_size=3, stride=2, activation="relu")
        self.face_conv2 = Conv(32, 64, kernel_size=3, stride=2, activation="relu")
        self.face_conv3 = Conv(64, 128, kernel_size=3, stride=2, activation="relu")

        self.audio_conv1 = Conv(1, 32, kernel_size=1, activation="relu")
        self.audio_conv2 = Conv(32, 32, kernel_size=3, activation="relu")
        self.audio_conv3 = Conv(32, 32, kernel_size=3, activation="relu")
        self.audio_conv4 = Conv(32, 64, kernel_size=3, activation="relu")

        self.fusion_conv1 = Conv(192, 256, kernel_size=3, activation="relu")
        self.resblock1 = ResBlock5d(256)
        self.resblock2 = ResBlock5d(256)
        self.resblock3 = ResBlock5d(256)

        self.upconv1 = Conv(256, 128, kernel_size=3, activation="relu")
        self.upconv2 = Conv(128, 64, kernel_size=3, activation="relu")
        self.upconv3 = Conv(64, 32, kernel_size=3, activation="relu")
        self.out_conv = Conv(32, 3, kernel_size=3, activation="tanh")

    def forward(self, face_sequences, mel_sequences):
        # face: (B, T, C, H, W) → (B, C, T, H, W)
        B, T, _C, _H, _W = face_sequences.shape
        face = face_sequences.permute(0, 2, 1, 3, 4)

        f = self.face_conv3(self.face_conv2(self.face_conv1(face)))

        m = mel_sequences.unsqueeze(2)
        m = self.audio_conv4(self.audio_conv3(self.audio_conv2(self.audio_conv1(m))))
        m = m.reshape(B, -1, T, m.shape[3], m.shape[4])
        m = F.interpolate(m, size=(f.shape[3], f.shape[4]),
                          mode="bilinear", align_corners=False)

        fused = self.fusion_conv1(torch.cat([f, m], dim=1))
        fused = self.resblock3(self.resblock2(self.resblock1(fused)))
        fused = self.upconv3(self.upconv2(self.upconv1(fused)))
        out = self.out_conv(fused)  # (B, 3, T, H, W)

        # Return center frame (index 2 of 5 temporal frames)
        return out[:, :, 2, :, :]


def export_to_onnx(pth_path: str | Path, output_path: str | Path,
                   simplify: bool = False) -> bool:
    """Convert wav2lip_gan.pth → wav2lip_gan.onnx."""
    pth_path = Path(pth_path)
    output_path = Path(output_path)

    if not pth_path.exists():
        print(f"[ERROR] Checkpoint not found: {pth_path}")
        print("  Download from: https://github.com/Rudrabha/Wav2Lip/releases")
        return False

    print(f"[1/3] Loading: {pth_path}")
    checkpoint = torch.load(pth_path, map_location="cpu", weights_only=False)

    if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state_dict = checkpoint["state_dict"]
    else:
        state_dict = checkpoint

    clean_state = {k.replace("module.", ""): v for k, v in state_dict.items()}

    print(f"[2/3] Building model ({len(clean_state)} keys)")
    model = Wav2Lip()
    _ = model.load_state_dict(clean_state, strict=False)
    _ = model.eval()

    dummy_face = torch.randn(1, 5, 6, 96, 96)
    dummy_mel  = torch.randn(1, 5, 80, 16)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[3/3] Exporting: {output_path}")
    _ = torch.onnx.export(
        model,
        (dummy_face, dummy_mel),
        str(output_path),
        input_names=["face_sequences", "mel_sequences"],
        output_names=["face_out"],
        dynamic_axes={
            "face_sequences": {0: "batch"},
            "mel_sequences":  {0: "batch"},
            "face_out":       {0: "batch"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    print(f"[OK] Saved: {output_path}")

    if simplify:
        try:
            import onnx
            import onnxsim  # pyright: ignore[reportMissingImports]
            print("Simplifying...")
            m = onnx.load(str(output_path))
            m2, _ = onnxsim.simplify(m)
            onnx.save(m2, str(output_path))
            print("[OK] Simplified")
        except ImportError:
            print("[WARN] pip install onnxsim — skipping")

    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Wav2Lip .pth → ONNX")
    _ = parser.add_argument("--checkpoint", "-c", default="models/wav2lip_gan.pth")
    _ = parser.add_argument("--output", "-o", default="models/wav2lip_gan.onnx")
    _ = parser.add_argument("--simplify", "-s", action="store_true")
    args = parser.parse_args()
    ok = export_to_onnx(args.checkpoint, args.output, args.simplify)
    sys.exit(0 if ok else 1)
