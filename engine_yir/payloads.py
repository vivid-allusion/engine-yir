"""Request-body construction — pure functions, no I/O.

Split out of ``engine.py`` so the mapping from (profile, catalogue entry, input
file) to a Yir request is testable on its own.

Yir's body is ``{model, input: {type, prompt, references: [{role, url}]},
parameters}``. Each model's contract lists, per input type, the reference roles
and the parameter values it takes; the catalogue carries that as
``[inputs.<type>]``. The rules:

* the input type follows what the item carries: declared slots make it
  ``reference``, primary pictures make it ``image`` with a start (and end)
  frame where the model takes ``first_frame``, otherwise reference pictures in
  whichever type takes ``reference_image``; a prompt alone makes it ``text``;
* only parameters the chosen type lists are sent, and only with a value it
  allows. Anything else is dropped with a visible warning — H3 Max's ``image``
  input takes ``aspect_ratio`` adaptive only, so a profile's 16:9 stays home;
* a duration outside the type's range refuses the item rather than quietly
  making a clip of another length.
"""

from __future__ import annotations

from typing import Any

from .catalog import NON_PAYLOAD_KEYS, EndpointSpec
from .datatypes import EngineError, InputFile

#: The declared slots a Video Generator fills, and the Yir role each becomes.
SLOT_ROLES = {
    "reference_images": "reference_image",
    "reference_videos": "reference_video",
    "reference_audios": "reference_audio",
}


def compose_prompt(profile: dict, item: InputFile) -> str:
    """``prompt_prefix`` + the file's prompt + ``prompt_suffix``, trimmed."""
    prefix = profile.get("prompt_prefix", "") or ""
    suffix = profile.get("prompt_suffix", "") or ""
    return f"{prefix}{item.prompt}{suffix}".strip()


def build_input(
    profile: dict,
    spec: EndpointSpec,
    params: dict,
    prompt: str,
    item: InputFile,
) -> tuple[dict, list[str]]:
    """Build Yir's ``input`` and ``parameters`` for one input file.

    Returns the body (without ``model``) and any advisory warnings. Raises
    ``EngineError`` for an item the model cannot take as it is.
    """
    if not spec.inputs:
        raise EngineError(f"{spec.model} is not in the Yir catalogue; its input types are unknown")
    kind, references = _pick_input(spec, item)
    allowed = spec.inputs[kind]
    params = dict(params)
    if item.metadata.get("duration") is not None:
        params["duration"] = item.metadata["duration"]

    warnings: list[str] = []
    parameters: dict[str, Any] = {}
    values = allowed.get("values") or {}
    for key, value in params.items():
        if key in NON_PAYLOAD_KEYS or key in SLOT_ROLES or key == "prompt" or is_unset(value):
            continue
        if key == "duration" and allowed.get("duration"):
            parameters[key] = _duration(value, allowed["duration"], spec.model, kind)
        elif key in values and (match := _allowed(value, values[key])) is not None:
            parameters[key] = match[0]
        else:
            takes = sorted(values) + (["duration"] if allowed.get("duration") else [])
            warnings.append(f"{spec.model} {kind} input does not take {key}={value!r} — not sent "
                            f"(it takes {', '.join(takes) or 'no parameters'})")

    body_input: dict[str, Any] = {"type": kind, "prompt": prompt}
    if references:
        body_input["references"] = references
    return {"input": body_input, "parameters": parameters}, warnings


def _pick_input(spec: EndpointSpec, item: InputFile) -> tuple[str, list[dict]]:
    """The input type and references for what the item carries."""
    urls = list(item.reference_urls)
    slots = {slot: list(u) for slot, u in (item.references or {}).items() if u}
    for slot in slots:
        if slot not in SLOT_ROLES:
            raise EngineError(f"{spec.model} has no reference slot '{slot}'")
    if slots:
        if urls:
            raise EngineError(f"{spec.model} cannot take a start picture together with "
                              f"reference slots ({item.path.name})")
        refs = [{"role": SLOT_ROLES[s], "url": u} for s, us in slots.items() for u in us]
        return _need(spec, "reference", refs), refs
    if urls:
        frames = _type_with_role(spec, "first_frame")
        if frames:
            if len(urls) > 2:
                raise EngineError(f"{spec.model} takes a start and an end picture; "
                                  f"{item.path.name} carries {len(urls)} links")
            return frames, [{"role": r, "url": u} for u, r in zip(urls, ("first_frame", "last_frame"))]
        kind = _type_with_role(spec, "reference_image")
        if not kind:
            raise EngineError(f"{spec.model} takes no pictures; {item.path.name} carries {len(urls)}")
        return kind, [{"role": "reference_image", "url": u} for u in urls]
    return _need(spec, "text", []), []


def _type_with_role(spec: EndpointSpec, role: str) -> str:
    return next((k for k, v in spec.inputs.items() if role in (v.get("roles") or ())), "")


def _need(spec: EndpointSpec, kind: str, refs: list[dict]) -> str:
    if kind not in spec.inputs:
        what = "a prompt alone" if kind == "text" else "reference slots"
        raise EngineError(f"{spec.model} cannot run from {what}; it takes "
                          f"{', '.join(sorted(spec.inputs))} input")
    roles = spec.inputs[kind].get("roles") or ()
    bad = sorted({r["role"] for r in refs} - set(roles))
    if bad:
        raise EngineError(f"{spec.model} {kind} input does not take {', '.join(bad)}")
    return kind


def _allowed(value: Any, choices: list) -> tuple[Any] | None:
    """The contract's own value matching ``value`` (``"16:9"`` or ``True`` from YAML)."""
    for choice in choices:
        if value == choice or str(value).lower() == str(choice).lower():
            return (choice,)
    return None


def _duration(value: Any, bounds: list, model: str, kind: str) -> int:
    low, high = bounds
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = None
    if seconds is None or not seconds.is_integer() or not low <= seconds <= high:
        raise EngineError(f"{model} {kind} input takes a duration of {low}-{high} whole seconds, "
                          f"not {value!r}")
    return int(seconds)


def is_unset(value: Any) -> bool:
    """True for a value that means "not set" rather than a real input."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple)) and not value:
        return True
    return False
