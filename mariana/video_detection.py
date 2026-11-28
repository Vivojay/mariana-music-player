"""Optional local YOLO ONNX detection, independent of the playback clock."""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import math
import threading
from pathlib import Path


def model_path(value):
    path = Path(value).expanduser().resolve(strict=True)
    if path.suffix.lower() != ".onnx" or not path.is_file() or not 0 < path.stat().st_size <= 160 * 1024 ** 2:
        raise ValueError("Choose a local ONNX detection model no larger than 160 MiB")
    return path


def runtime_available():
    return importlib.util.find_spec("onnxruntime") is not None


def _names(value):
    if not isinstance(value, str) or len(value) > 16_384:
        return {}
    try:
        names = ast.literal_eval(value)
    except (ValueError, SyntaxError, RecursionError):
        return {}
    if isinstance(names, list):
        names = dict(enumerate(names))
    if not isinstance(names, dict):
        return {}
    return {key: name for key, name in names.items()
            if type(key) is int and 0 <= key < 256 and isinstance(name, str) and 0 < len(name) <= 48 and name.isprintable()}


class YoloDetector:
    """Read raw detect output [1, 4+classes, candidates] and apply class-aware NMS."""

    def __init__(self, path, *, session=None):
        if session is None:
            import onnxruntime as ort  # pyright: ignore[reportMissingImports]

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.enable_mem_pattern = False
            session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        (source,) = session.get_inputs()
        self.session = session
        self.input = source.name
        self.names = _names(session.get_modelmeta().custom_metadata_map.get("names"))
        shape = source.shape
        if source.type != "tensor(float)" or len(shape) != 4 or shape[:2] != [1, 3]:
            raise ValueError("Use an Ultralytics detection export with one RGB image input")
        self.height, self.width = shape[-2:]
        if not all(type(size) is int and 160 <= size <= 960 for size in (self.height, self.width)):
            raise ValueError("Use a fixed ONNX input between 160 and 960 pixels per side")

    def detect(self, image):
        import numpy as np
        from PIL import Image

        width, height = image.size
        scale = min(self.width / width, self.height / height)
        scaled = (max(1, round(width * scale)), max(1, round(height * scale)))
        offset_x, offset_y = ((self.width - scaled[0]) // 2, (self.height - scaled[1]) // 2)
        input_image = Image.new("RGB", (self.width, self.height), (114, 114, 114))
        input_image.paste(image.resize(scaled, Image.Resampling.BILINEAR), (offset_x, offset_y))
        tensor = np.asarray(input_image, dtype=np.float32).transpose(2, 0, 1)[None] / 255
        outputs = self.session.run(None, {self.input: np.ascontiguousarray(tensor)})
        if len(outputs) != 1:
            raise ValueError("Use a detection-only export with integrated NMS turned off")
        raw = outputs[0]
        if raw.ndim != 3 or raw.shape[0] != 1 or not 5 <= raw.shape[1] <= 260 or not 1 <= raw.shape[2] <= 50_000:
            raise ValueError("Only raw YOLO object-detection ONNX exports are supported")
        predictions = raw[0].T
        scores = predictions[:, 4:]
        classes = scores.argmax(axis=1)
        confidence = scores[np.arange(scores.shape[0]), classes]
        eligible = np.flatnonzero((confidence >= .45) & (confidence <= 1))
        ranked = eligible[np.argsort(-confidence[eligible], kind="stable")][:160]
        boxes = []
        for i in ranked:
            cx, cy, w, h = map(float, predictions[i, :4])
            if not all(map(math.isfinite, (cx, cy, w, h))) or min(w, h) <= 0:
                continue
            coords = tuple(min(1., max(0., value)) for value in (
                (cx - w / 2 - offset_x) / scaled[0], (cy - h / 2 - offset_y) / scaled[1],
                (cx + w / 2 - offset_x) / scaled[0], (cy + h / 2 - offset_y) / scaled[1],
            ))
            if coords[0] >= coords[2] or coords[1] >= coords[3]:
                continue
            category = int(classes[i])
            if any(category == previous[0] and _overlap(coords, previous[3]) > .45 for previous in boxes):
                continue
            boxes.append((category, self.names.get(category, f"Class {category}"), float(confidence[i]), coords))
            if len(boxes) == 36:
                break
        return tuple(boxes)


def _overlap(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    total = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / total if total else 0


class LiveDetection:
    """A single worker with replaceable frames and generation-scoped results."""

    def __init__(self):
        self.condition = threading.Condition()
        self.config = (0, None)
        self.pending = None
        self.result = None
        self.state = "off"
        self.worker = threading.Thread(target=self._run, name="mariana-picture-detector", daemon=True)
        self.worker.start()

    def select(self, version, path):
        with self.condition:
            if self.config == (version, path):
                return
            self.config = (version, path)
            self.pending = self.result = None
            self.state = "loading" if path else "off"
            self.condition.notify()

    def offer(self, image, identity, timestamp):
        with self.condition:
            if self.config[1] and self.state == "ready":
                self.pending = (image, identity, timestamp)
                self.condition.notify()
                return True
        return False

    def snapshot(self):
        with self.condition:
            return self.state, self.result

    def _run(self):
        active = (0, None)
        detector = None
        while True:
            with self.condition:
                self.condition.wait_for(lambda current=active: self.config != current or self.pending is not None)
                configuration = self.config
                frame, self.pending = self.pending, None
            if active != configuration:
                active = configuration
                detector = None
                if configuration[1]:
                    with contextlib.suppress(Exception):
                        detector = YoloDetector(model_path(configuration[1]))
                    with self.condition:
                        if self.config == configuration:
                            self.state = "ready" if detector else "error"
                continue
            if detector and frame:
                image, identity, position = frame
                try:
                    boxes = detector.detect(image)
                except Exception:
                    boxes = None
                with self.condition:
                    if self.config == configuration:
                        self.result = (identity, position, boxes) if boxes is not None else None
                        if boxes is None:
                            self.state = "error"
