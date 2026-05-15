"""xAI (Grok) schema transforms.

xAI explicitly marks ``logit_bias`` as unsupported.  Strip it before
sending upstream to avoid errors.

References:
    https://docs.x.ai/docs/api-reference#chat-completions
"""

from llm_rosetta.shims.transforms import strip_fields

to_transforms = (strip_fields("logit_bias"),)
from_transforms = ()
