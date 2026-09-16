"""Minimal reusable J-space intervention primitives.

This module exists because the exact same causal write is now used by the
released probe-swap calibration and the multilingual bridge experiment.  Keep
it small: coordinate swap plus a norm-matched random falsification control.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Iterable

import torch


def _replace_hidden(output, hidden):
    if torch.is_tensor(output):
        return hidden
    if isinstance(output, tuple):
        return (hidden, *output[1:])
    if isinstance(output, list):
        return [hidden, *output[1:]]
    raise TypeError(f"Unsupported block output type: {type(output)!r}")


def deterministic_random_unit(d_model: int, *, seed: int, key: str) -> torch.Tensor:
    digest = hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()
    local_seed = int.from_bytes(digest[:8], "big") % (2**63 - 1)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(local_seed)
    vector = torch.randn(d_model, generator=generator, dtype=torch.float32)
    return vector / vector.norm().clamp_min(1e-12)


def _layer_basis(model, lens, layer: int, source_id: int, target_id: int):
    unembedding = model._lm_head.weight[[source_id, target_id]].detach().float().cpu()
    jacobian = lens.jacobians[layer].float().cpu()
    source_direction = jacobian.T @ unembedding[0]
    target_direction = jacobian.T @ unembedding[1]
    basis = torch.stack([source_direction, target_direction], dim=1)
    return basis, torch.linalg.pinv(basis)


@contextmanager
def jspace_swap(
    model,
    lens,
    source_id: int,
    target_id: int,
    layers: Iterable[int],
    *,
    strength: float = 1.0,
    mode: str = "coordinate_swap",
    seed: int = 1729,
    key: str = "",
    position_limit: int | None = None,
):
    """Patch a J-space coordinate swap into selected residual blocks.

    ``coordinate_swap`` implements the released two-coordinate intervention:

        V = [J_l^T w_source, J_l^T w_target]
        c = V^+ h
        h' = h + strength * V * (swap(c) - c)

    ``random_norm_matched`` uses the exact per-position norm of that swap delta
    but applies it along a deterministic random unit direction.  This controls
    for generic activation displacement.

    ``position_limit`` patches only sequence positions ``[:position_limit]``.
    This is useful when candidate continuations are teacher-forced: the hidden
    bridge is edited in the prompt, not in the answer tokens themselves.
    """
    layer_list = [int(layer) for layer in layers]
    if not layer_list:
        raise ValueError("jspace_swap requires at least one layer")
    missing = [layer for layer in layer_list if layer not in lens.source_layers]
    if missing:
        raise ValueError(f"Layers are not present in fitted lens: {missing}")
    if mode not in {"coordinate_swap", "random_norm_matched"}:
        raise ValueError(f"Unknown J-space intervention mode: {mode}")

    bases = {
        layer: _layer_basis(model, lens, layer, source_id, target_id)
        for layer in layer_list
    }
    random_units = {
        layer: deterministic_random_unit(
            model.d_model,
            seed=seed,
            key=f"{key}|{source_id}|{target_id}|{layer}|{mode}",
        )
        for layer in layer_list
    }

    handles = []
    try:
        for layer in layer_list:
            basis_cpu, pinv_cpu = bases[layer]
            random_cpu = random_units[layer]

            def hook(
                _module,
                _inputs,
                output,
                basis_cpu=basis_cpu,
                pinv_cpu=pinv_cpu,
                random_cpu=random_cpu,
            ):
                hidden = output if torch.is_tensor(output) else output[0]
                work = hidden.float()
                stop = work.shape[-2] if position_limit is None else min(position_limit, work.shape[-2])
                if stop <= 0:
                    return output

                selected = work[..., :stop, :]
                basis = basis_cpu.to(selected.device)
                pinv = pinv_cpu.to(selected.device)
                coordinates = selected @ pinv.T
                swapped = coordinates.flip(-1)
                raw_delta = (swapped - coordinates) @ basis.T

                if mode == "coordinate_swap":
                    delta = raw_delta
                else:
                    random_unit = random_cpu.to(selected.device)
                    magnitudes = raw_delta.norm(dim=-1, keepdim=True)
                    delta = magnitudes * random_unit.view(*([1] * (selected.ndim - 1)), -1)

                patched = work.clone()
                patched[..., :stop, :] = selected + strength * delta
                return _replace_hidden(output, patched.to(hidden.dtype))

            handles.append(model.layers[layer].register_forward_hook(hook))
        yield
    finally:
        for handle in handles:
            handle.remove()
