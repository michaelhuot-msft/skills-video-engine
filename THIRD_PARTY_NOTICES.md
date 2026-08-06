# Third-party notices

The project source is MIT licensed. The container includes independently
licensed components:

| Component | Version or revision | License |
| --- | --- | --- |
| HyperFrames | 0.7.82 | Apache-2.0 |
| Kokoro Python package | 0.9.4 | Apache-2.0 |
| Kokoro-82M model | `f3ff3571791e39611d31c381e3a41a3af07b4987` | Apache-2.0 |
| kokoro-onnx Python package | 0.5.0 | MIT |
| Kokoro ONNX model and voices | 1.0 | Apache-2.0 |
| FFmpeg and Debian codec libraries | Debian Bookworm package version at build time | GPL/LGPL, depending on component |
| x264 | Debian Bookworm package version at build time | GPL-2.0-or-later |
| Chromium and chrome-headless-shell | See image SBOM | BSD-3-Clause and other licenses |

The exact Debian FFmpeg and x264 source packages used by each image build are
included under `/usr/src/third-party`. Image SBOM and provenance attestations
are published with release images.

This notice is informational and is not legal advice. Consult each component's
license text for its complete terms.
