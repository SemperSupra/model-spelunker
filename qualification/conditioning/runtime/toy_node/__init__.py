"""Tiny, deterministic Torch CNN model for ComfyUI build/runtime qualification.

NO trained checkpoint; NO external model files; NO quality/performance claims.
The model exists only to prove real torch module execution, node graph and PNG save.
"""
import torch
import torch.nn as nn

class TinyTorchConditionerFixture:
    CATEGORY = "testing/qualification"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE",)
    DESCRIPTION = "Synthetic one-layer CNN fixture. Not a text-to-image generative model."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 1, "min": 0, "max": 2147483647}),
            "variant": (["base", "modified"],),
            "size": ("INT", {"default": 64, "min": 32, "max": 128, "step": 16}),
        }}

    def run(self, seed, variant, size):
        if variant not in ("base", "modified") or not 32 <= size <= 128:
            raise ValueError("invalid toy fixture variant or dimensions")
        generator = torch.Generator(device="cpu").manual_seed(seed)
        noise = torch.rand((1, 3, size, size), generator=generator)
        toy_model = nn.Conv2d(3, 3, kernel_size=1, bias=True)
        with torch.no_grad():
            matrix = torch.tensor([
                [0.7, 0.2, 0.1], [0.1, 0.7, 0.2], [0.2, 0.1, 0.7]
            ], dtype=torch.float32)
            if variant == "modified":
                matrix = torch.tensor([
                    [0.1, 0.7, 0.2], [0.7, 0.2, 0.1], [0.2, 0.1, 0.7]
                ], dtype=torch.float32)
            toy_model.weight.copy_(matrix.reshape(3, 3, 1, 1))
            toy_model.bias.zero_()
            pixels = toy_model(noise).clamp(0, 1).permute(0, 2, 3, 1)
        return (pixels.contiguous(),)

NODE_CLASS_MAPPINGS = {"TinyTorchConditionerFixture": TinyTorchConditionerFixture}
NODE_DISPLAY_NAME_MAPPINGS = {
    "TinyTorchConditionerFixture": "Tiny Torch Conditioner (Build Fixture ONLY)"
}
