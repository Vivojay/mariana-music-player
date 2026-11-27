"""Presentation-only video transforms. All presets share one data file."""
from functools import lru_cache
import json
from pathlib import Path

PRESETS = json.loads(Path(__file__).with_name("video_filters.json").read_text(encoding="utf-8"))
LUMA = (0.2126, 0.7152, 0.0722)
ALIASES = {"none": "off", "grey": "grayscale", "b&w": "threshold", "bw": "threshold", "black-white": "threshold"}
DEFAULT = ("off", 50)


def parse_filter(preset, threshold=None):
    if not isinstance(preset, str):
        raise ValueError("Choose a video filter from video filter list")
    preset = ALIASES.get(preset.casefold(), preset.casefold())
    if preset not in PRESETS:
        raise ValueError("Choose a video filter from video filter list")
    if threshold is None:
        return preset, 50
    if preset != "threshold" or not isinstance(threshold, (str, int)) or type(threshold) is bool:
        raise ValueError("Only threshold accepts a whole number from 0 to 100")
    text = str(threshold)
    if not text.isascii() or not text.isdecimal() or len(text) > 3 or int(text) > 100:
        raise ValueError("Threshold must be a whole number from 0 to 100")
    return preset, int(text)


def projection(selection):
    return {"preset": selection[0], "threshold": selection[1]}


@lru_cache(maxsize=1)
def _transfer_tables():
    import numpy as np

    srgb = np.linspace(0, 1, 256, dtype=np.float32)
    linear = np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)
    domain = np.linspace(0, 1, 65_536, dtype=np.float32)
    to_srgb = np.where(domain <= .0031308, 12.92 * domain, 1.055 * domain ** (1 / 2.4) - .055)
    return linear, np.rint(to_srgb * 255).astype(np.uint8)


@lru_cache(maxsize=32)
def _parameters(selection):
    preset, threshold = selection
    spec = PRESETS[preset]
    kind = spec["kind"]
    if kind == "threshold":
        return tuple(255 if n / 255 >= threshold / 100 else 0 for n in range(256))
    if kind == "matrix":
        source = spec["matrix"]
        return tuple(value for i in range(0, 9, 3) for value in (*source[i:i + 3], 0))
    if kind == "duotone":
        return tuple(value for lo, hi in zip(spec["low"], spec["high"], strict=True)
                     for value in (*(weight * (hi - lo) for weight in LUMA), lo * 255))
    if kind == "contrast":
        return tuple(min(255, max(0, round((value - 127.5) * 1.5 + 127.5))) for value in range(256)) * 3
    if kind == "linear-matrix":
        import numpy as np

        return np.array(spec["matrix"], dtype=np.float32).reshape(3, 3)
    return None


def filter_image(image, selection):
    """Transform one decoded RGB frame without touching the audio or source."""
    kind = PRESETS[selection[0]]["kind"]
    values = _parameters(selection)
    if kind in {"matrix", "duotone"}:
        return image.convert("RGB", values)
    if kind == "threshold":
        return image.convert("L", (*LUMA, 0)).point(values).convert("RGB")
    if kind == "contrast":
        return image.point(values)
    if kind == "invert":
        from PIL import ImageOps

        return ImageOps.invert(image)
    if kind == "linear-matrix":
        import numpy as np
        from PIL import Image

        linear, to_srgb = _transfer_tables()
        rgb = linear[np.asarray(image)]
        result = np.einsum("...c,rc->...r", rgb, values)
        indexes = np.rint(np.clip(result, 0, 1) * (len(to_srgb) - 1)).astype(np.uint16)
        return Image.fromarray(to_srgb[indexes])
    return image
