"""Offline plug-in renderer. Third-party DSP runs outside Mariana's audio process."""
from __future__ import annotations

import sys


def main(argv):
    if len(argv) != 3:
        return 2
    import numpy as np
    from pedalboard import load_plugin  # pyright: ignore[reportMissingImports]
    from pedalboard.io import AudioFile  # pyright: ignore[reportMissingImports]

    plugin_path, source, output = argv
    effect = load_plugin(plugin_path)
    if not effect.is_effect:
        raise ValueError("Choose an audio effect plug-in.")
    with AudioFile(source) as reader, AudioFile(output, "w", reader.samplerate, reader.num_channels) as writer:
        written = 0
        while reader.tell() < reader.frames:
            samples = reader.read(min(16384, reader.frames - reader.tell()))
            if not samples.shape[-1]:
                raise ValueError("Input ended before the reported duration.")
            wet = effect.process(samples, reader.samplerate, reset=False)
            if wet.shape[-1]:
                writer.write(wet)
                written += wet.shape[-1]
        # Delay compensation may retain samples until further input is supplied.
        # Bound plug-ins that cannot produce output, and keep the source duration.
        extra = 0
        while written < reader.frames:
            remaining = reader.frames - written
            chunk = min(16384, remaining)
            zeros = np.zeros((reader.num_channels, chunk), dtype=np.float32)
            wet = effect.process(zeros, reader.samplerate, reset=False)[..., :remaining]
            if wet.shape[-1]:
                writer.write(wet)
                written += wet.shape[-1]
            else:
                extra += chunk
                if extra > reader.samplerate * 10:
                    raise ValueError("Plug-in did not return its delayed samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
