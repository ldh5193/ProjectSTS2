"""Export a trained MaskablePPO policy to ONNX so the mod can run
inference natively in C# (Microsoft.ML.OnnxRuntime).

Input shape:  (batch, 64)   — observation
Output:        action_logits (batch, 300)  — pre-softmax, pre-mask
The mod is responsible for masking + argmax in C#.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\export_onnx.py `
        --model models\\sweeps\\tank\\final.zip `
        --out tools\\STS2MCP-bin\\policy.onnx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch
import torch.nn as nn
from sb3_contrib import MaskablePPO

from sim.action_space import N_ACTIONS
from sim.env_run import OBS_DIM


class _MaskablePPOForOnnx(nn.Module):
    """Thin wrapper exposing the policy net's action_logits forward
    without action sampling or value head, suited to ONNX export."""

    def __init__(self, sb3_model: MaskablePPO):
        super().__init__()
        self.policy = sb3_model.policy

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        # MaskablePPO.policy.forward returns (actions, values, log_prob);
        # we want the *unmasked* action distribution logits. The simplest
        # accessor across SB3 versions: extract features then run the
        # action net manually.
        features = self.policy.extract_features(
            obs, self.policy.pi_features_extractor
        )
        latent_pi = self.policy.mlp_extractor.forward_actor(features)
        action_logits = self.policy.action_net(latent_pi)
        return action_logits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True,
                        help="Path to MaskablePPO .zip checkpoint.")
    parser.add_argument("--out", type=Path,
                        default=Path("tools/STS2MCP-bin/policy.onnx"),
                        help="Where to write the .onnx file. Lands in the mod's "
                             "bin dir so deploy is just one file.")
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.model}")
    sb3 = MaskablePPO.load(args.model, device="cpu")
    print(f"  policy: {type(sb3.policy).__name__}")
    print(f"  obs_dim: {OBS_DIM}  action_dim: {N_ACTIONS}")

    wrapper = _MaskablePPOForOnnx(sb3).eval()
    dummy = torch.zeros(1, OBS_DIM, dtype=torch.float32)

    print(f"Exporting to {args.out}  (opset {args.opset})")
    torch.onnx.export(
        wrapper,
        dummy,
        str(args.out),
        export_params=True,
        opset_version=args.opset,
        do_constant_folding=True,
        input_names=["obs"],
        output_names=["action_logits"],
        dynamic_axes={
            "obs": {0: "batch"},
            "action_logits": {0: "batch"},
        },
    )
    # The newer torch.onnx exporter spills weights to a sidecar
    # `<name>.onnx.data` whenever they're "large enough." For a ~100KB
    # MLP we'd rather ship a single file, so collapse external weights
    # back into the main .onnx and remove the sidecar.
    _embed_external_weights(args.out)

    size = args.out.stat().st_size
    print(f"Done. {args.out} = {size:,} bytes")


def _embed_external_weights(onnx_path: Path) -> None:
    """Re-save the model with all initializers embedded (no .data sidecar).
    Idempotent and safe to call on a model that already has them embedded."""
    import onnx
    from onnx import external_data_helper

    model = onnx.load(str(onnx_path), load_external_data=True)
    # Force every initializer back into the graph proto itself.
    for tensor in model.graph.initializer:
        external_data_helper.uses_external_data(tensor)  # noop call
    # Convert any external-data initializers to inline raw_data.
    for tensor in model.graph.initializer:
        if tensor.HasField("data_location") \
                and tensor.data_location == onnx.TensorProto.EXTERNAL:
            external_data_helper.load_external_data_for_tensor(
                tensor, str(onnx_path.parent))
            tensor.ClearField("data_location")
            tensor.ClearField("external_data")
    onnx.save(model, str(onnx_path))
    # Clean up sidecar if present.
    sidecar = onnx_path.with_suffix(onnx_path.suffix + ".data")
    if sidecar.exists():
        sidecar.unlink()
        print(f"  removed external sidecar {sidecar.name}")


if __name__ == "__main__":
    main()
