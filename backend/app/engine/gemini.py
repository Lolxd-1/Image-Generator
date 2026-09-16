"""Vertex AI express-mode Gemini client: error classification and response parsing, ported verbatim from main.py.

The marker tuples and the two parsing helpers (`finish_reason`,
`extract_image_bytes`) are copied character-for-character from main.py's
ImageGenerator — they were tuned by hand against real free-tier error text and
must not be "cleaned up".
"""
import hashlib
import logging

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

VISION_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-3.1-flash-lite-image"
ASPECT_RATIO = "1:1"
IMAGE_SIZE = "1K"          # flash-lite-image supports 1K only; 2K/4K -> HTTP 400
API_TIMEOUT = 90


class RateLimited(Exception):
    """The API rejected the call as a 429 / quota / rate-limit error."""


class AuthFailure(Exception):
    """The API key is invalid, unauthenticated, or otherwise unusable."""


class NoImage(Exception):
    """The call succeeded but the response carried no inline image data."""


# main.py lines 334-341, verbatim.
_RATE_MARKERS = (
    "429", "resource_exhausted", "resource has been exhausted",
    "quota", "rate limit", "too many requests",
)
_AUTH_MARKERS = (
    "401", "403", "unauthenticated", "permission_denied", "api key not valid",
    "invalid api key", "billing", "has not been used in project", "is disabled",
)


def key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:32]


def build_client(api_key: str):
    # vertexai=True + api_key  ->  Vertex AI express mode. A plain
    # genai.Client(api_key=...) hits the wrong endpoint and 404s.
    return genai.Client(
        vertexai=True,
        api_key=api_key,
        http_options=types.HttpOptions(timeout=API_TIMEOUT * 1000),
    )


def is_rate_limit(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in _RATE_MARKERS)


def is_auth_error(msg: str) -> bool:
    m = msg.lower()
    if is_rate_limit(msg):
        return False
    return any(k in m for k in _AUTH_MARKERS)


def finish_reason(resp) -> str:
    try:
        for c in (resp.candidates or []):
            fr = getattr(c, "finish_reason", None)
            if fr is not None:
                return str(fr)
    except Exception:
        pass
    return "UNKNOWN"


def extract_image_bytes(resp) -> bytes | None:
    """Pull the first inline image out of a generate_content response."""
    try:
        for c in (resp.candidates or []):
            content = getattr(c, "content", None)
            if not content:
                continue
            for p in (content.parts or []):
                inline = getattr(p, "inline_data", None)
                if inline is not None and inline.data:
                    return inline.data
    except Exception as e:
        logger.warning(f"  Could not parse response parts: {e}")
    return None
