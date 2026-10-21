# License review

Items the founder should review. The engine in `packages/messer-core/` derives from Timbal
(Apache-2.0, upstream `github.com/timbal-ai/timbal`, tag `v2.7.39`, commit `45f3298899f32f861f8573c918ae22bdf90e489f`).
Attribution is in `NOTICE`; the original Apache-2.0 text is kept in `LICENSE` and `packages/messer-core/LICENSE`.

| Path | Origin / license | Notes |
|---|---|---|
| `packages/messer-core/python/` | Timbal, Apache-2.0 | Renamed and modified; see headers "Modified by Messer". |
| `packages/messer-core/cli/` (Zig) | Timbal, Apache-2.0 (repository license; no per-file headers) | Zig CLI renamed to `messer`. Zig toolchain is not available in the build environment; the Messer CLI commands (`create/start/push/deploy/evals`) are also provided in Python (`messer-cli`). |
| `packages/messer-core/tui/` (Rust) | Timbal, `Cargo.toml` declares Apache-2.0 | Includes `src/screens/ace/` ("ACE" playground, policies, evals screens). The ACE backend subproject referenced by upstream's `pyproject.toml` (`[tool.uv.workspace] members = ["ace"]`) was **not present** at the pinned tag; its license is unknown. |
| `packages/messer-core/benchmarks/*/package-lock.json` | Third-party npm dependency locks (MIT/Apache mostly) | Only used for benchmarks; not shipped. |
| `packages/messer-core/benchmarks/voice/`, `scripts/prepare_ambience.py` | Timbal, Apache-2.0 | Ambience audio is generated/downloaded at runtime; no audio files are vendored. |
| Voice turn-detection / VAD models downloaded at runtime | Hugging Face: `videosdk-live/Namo-Turn-Detector-v1-*`, `pipecat-ai/smart-turn-v3`, `onnx-community/silero-vad` | Model licenses must be checked before production use (they are not vendored in this repository). |
| `packages/messer-core/docs/images/*.png` (removed) | Upstream platform screenshots | Removed because they showed the upstream product UI; unused by the docs. |
| `packages/messer-core/docs/logo/*`, `docs/favicon.png` | Replaced with Messer assets | Original logos removed. |
| `packages/messer-core/docs/api-reference/` | Upstream platform API reference (Apache-2.0) | Describes the upstream hosted platform; superseded by Messer's generated OpenAPI reference in `docs/api/`. Kept for completeness. |
| Docling (document parsing, optional) | MIT | Installed only in the worker image (`messer-worker[docling]`). |
| fastembed + `intfloat/multilingual-e5-small` model | Apache-2.0 / MIT | Downloaded at build time of the worker image when available. |

No GPL/AGPL code has been copied into the repository.
