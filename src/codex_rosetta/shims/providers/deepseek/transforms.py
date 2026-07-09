"""DeepSeek schema transforms.

DeepSeek does not support the ``n``, ``logit_bias``, or ``seed`` fields
in chat completions.  Strip them before sending upstream to avoid errors.

References:
    https://api-docs.deepseek.com/api/create-chat-completion
"""

from codex_rosetta.shims.transforms import strip_fields

to_transforms = (strip_fields("n", "logit_bias", "seed"),)
from_transforms = ()
