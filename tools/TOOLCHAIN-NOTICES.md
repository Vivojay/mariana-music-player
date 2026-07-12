# Mariana managed-tool notices

The managed media-tool archive is assembled from independently licensed upstream projects. The archive metadata in `toolchain-sources.json` records the exact source or release asset and SHA-256 used by the build.

- **FFmpeg 8.1.2** is built with Mariana's LGPL-only configuration (`--disable-gpl --disable-nonfree`) and is distributed under LGPL-2.1-or-later. Source: <https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz>
- **Chromaprint/fpcalc 1.6.0** is distributed under LGPL-2.1-or-later. Source and license: <https://github.com/acoustid/chromaprint/tree/v1.6.0>
- **Deno 2.9.2** is distributed under the MIT license. Source and license: <https://github.com/denoland/deno/tree/v2.9.2>
- **rsgain 3.7** is distributed under the BSD 2-Clause license. Source and license: <https://github.com/complexlogic/rsgain/tree/v3.7>
- **libopus** is distributed under its BSD-style license and **LAME/libmp3lame** under LGPL-2.0-or-later; both are linked only into the separately distributed LGPL FFmpeg toolchain for Ogg Opus and MP3 broadcasting.

Mariana does not combine these executables into its own program. They remain separate programs invoked through subprocess interfaces. Complete corresponding FFmpeg source is referenced by the pinned source URL and published beside release provenance.
