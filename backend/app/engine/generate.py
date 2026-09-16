"""Single-shot dish image generation against Gemini's image model, ported from main.py's ImageGenerator.generate.

`generate_one` makes exactly ONE API attempt and raises a typed exception on
failure — all retry/backoff/fallback-prompt looping from the original CLI tool
is removed here; that policy now lives in the `/step` caller (see SPEC.md §6),
since each attempt here is one HTTP request rather than one iteration of an
in-process loop.
"""
from io import BytesIO

from PIL import Image
from google.genai import types

from app.engine import gemini

OUTPUT_SIZE = 1024
JPEG_QUALITY = 100


# main.py:94 resized the reference to 256x256 before EVERY call, with the
# comment "saves tokens". That matters more here, not less: a run sends the
# same reference alongside all ~100 prompts, so shipping a full-resolution
# photo multiplies input cost by 100 and slows every paced call.
REFERENCE_MAX_DIM = 256


def prepare_reference(data: bytes) -> bytes:
    """Downscale a stored reference to the square thumbnail the model expects."""
    img = Image.open(BytesIO(data)).convert("RGB")
    img = img.resize((REFERENCE_MAX_DIM, REFERENCE_MAX_DIM), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def generate_one(client, prompt: str, ref_jpeg: bytes) -> bytes:
    """Make one Gemini image-generation call. Returns raw model image bytes.

    Raises `gemini.RateLimited`, `gemini.AuthFailure`, or `gemini.NoImage`.
    Any other exception from the SDK call propagates unchanged.
    """
    ref_part = types.Part.from_bytes(data=ref_jpeg, mime_type="image/jpeg")
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio=gemini.ASPECT_RATIO,
            image_size=gemini.IMAGE_SIZE,
        ),
    )

    try:
        resp = client.models.generate_content(
            model=gemini.IMAGE_MODEL,
            contents=[ref_part, prompt],
            config=config,
        )
    except Exception as e:
        msg = str(e)
        if gemini.is_rate_limit(msg):
            raise gemini.RateLimited(msg[:300]) from e
        if gemini.is_auth_error(msg):
            raise gemini.AuthFailure(msg[:300]) from e
        raise

    raw = gemini.extract_image_bytes(resp)
    if raw:
        return raw

    # Response arrived but carried no image (safety block / text-only).
    reason = gemini.finish_reason(resp)
    try:
        text = (resp.text or "")[:160]
    except Exception:
        text = ""
    raise gemini.NoImage(f"no image (finish_reason={reason}, text={text!r})")


def to_jpeg(raw: bytes) -> tuple[bytes, int, int]:
    """Resize model output to OUTPUT_SIZE square JPEG. One-shot, no loops."""
    img = Image.open(BytesIO(raw)).convert("RGB")
    img = img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), OUTPUT_SIZE, OUTPUT_SIZE
