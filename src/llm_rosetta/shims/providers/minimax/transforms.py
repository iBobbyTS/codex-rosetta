"""MiniMax schema transforms.

MiniMax's OpenAI-compatible endpoint does not list ``logprobs``,
``top_logprobs``, ``seed``, or ``stop`` in its OpenAPI spec.
Strip them to avoid potential errors.

``presence_penalty``, ``frequency_penalty``, and ``logit_bias`` are
silently ignored (no error) so we do not strip them here.

References:
    https://platform.minimaxi.com/document/ChatCompletion%20v2
"""

from llm_rosetta.shims.transforms import strip_fields

to_transforms = (strip_fields("logprobs", "top_logprobs", "seed", "stop"),)
from_transforms = ()
