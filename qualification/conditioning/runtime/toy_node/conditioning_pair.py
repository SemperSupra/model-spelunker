"""Strictly synthetic two-module text-conditioning / image-production interface.

Purpose: exercise a real torch.nn.Embedding -> tensor ABI -> independent
torch.nn.Conv2d model inside ComfyUI's DAG. Deliberately untrained, tiny and
not a language model, diffusion generator, quality evaluator or Heretic model.
"""
from __future__ import annotations
import torch
from torch import nn


class TinyTextEncoderFixture:
    CATEGORY = "testing/qualification"
    FUNCTION = "condition"
    RETURN_TYPES = ("TOY_EMBED",)
    RETURN_NAMES = ("embedding",)
    DESCRIPTION = "Synthetic tiny Torch text-embedding ABI fixture. Not an LLM."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": (["red-square", "blue-circle"],),
            "variant": (["base", "modified"],),
        }}

    def condition(self, prompt: str, variant: str):
        if prompt not in ("red-square", "blue-circle") or variant not in ("base", "modified"):
            raise ValueError("SYNTHETIC_CONDITION_INPUT_DENIED")
        model = nn.Embedding(2, 3)
        with torch.no_grad():
            model.weight.copy_(torch.tensor([[0.9, 0.1, 0.3], [0.2, 0.7, 0.4]]))
            index = 0 if prompt == "red-square" else 1
            embedding = model(torch.tensor([index], dtype=torch.long))
            if variant == "modified":
                # Small deterministic treatment perturbation, not a trained edit.
                embedding = embedding[:, [1, 2, 0]]
        return (embedding.detach(),)


class TinyConditionedImageFixture:
    CATEGORY = "testing/qualification"
    FUNCTION = "render"
    RETURN_TYPES = ("IMAGE",)
    DESCRIPTION = "Synthetic deterministic Torch Conv2d conditioned by toy embedding."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "embedding": ("TOY_EMBED",),
            "seed": ("INT", {"default": 71, "min": 0, "max": 2147483647}),
            "size": ("INT", {"default": 64, "min": 32, "max": 128, "step": 16}),
        }}

    def render(self, embedding, seed: int, size: int):
        if (type(seed) is not int or type(size) is not int or seed < 0 or
            seed > 2147483647 or size < 32 or size > 128 or size % 16):
            raise ValueError("SYNTHETIC_RENDER_BOUNDS")
        if (not torch.is_tensor(embedding) or embedding.dtype != torch.float32 or
            tuple(embedding.shape) != (1, 3) or not bool(torch.isfinite(embedding).all())):
            raise ValueError("CONDITIONING_TENSOR_ABI_DENIED")
        model = nn.Conv2d(3, 3, kernel_size=1, bias=False)
        with torch.no_grad():
            model.weight.copy_(torch.eye(3).reshape(3, 3, 1, 1))
            noise = torch.rand((1, 3, size, size), generator=torch.Generator(device="cpu").manual_seed(seed))
            signal = embedding.detach().reshape(1, 3, 1, 1)
            # One deterministic image tensor from a distinct generation module.
            image = torch.sigmoid(model(noise) * 0.3 + signal * 1.2)
        return (image.permute(0, 2, 3, 1).contiguous(),)
