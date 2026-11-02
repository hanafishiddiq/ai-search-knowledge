# Research example: local video generation with 12 GB GPU memory

Prepared 2026-11-02 from source snapshots retrieved 2026-11-01. This original worked example chooses an investigation path, not a validated model or a current hardware guarantee.

## Constraints

Illustrative project: one local CUDA GPU with 12 GB VRAM, short image-to-video clips, optionally synchronized audio, and eventual commercial use. Exact GPU generation, resolution, clip duration and acceptable wait time must be fixed before judging fit. Twelve gigabytes is a hard example constraint; no candidate may be declared compatible from checkpoint labels, attention savings or unrelated hardware timings.

## Candidates and evidence

| Candidate | Supported facts | Consequence for this constraint |
| --- | --- | --- |
| LTX 2.5 | Its card describes locally hosted joint video/audio from text, image or video, a distilled eight-step checkpoint and Comfy-specific INT8/convrot assets. The Python route recommends CUDA 12.7+, Python 3.12+ and a different checkpoint path. Access is gated and community-license terms apply. [Model card](https://huggingface.co/Lightricks/LTX-2.5), publication date unknown; retrieved 2026-11-01. | Best-documented first experiment among these records, but no cited complete-pipeline 12 GB peak-memory result. An INT8 file does not by itself prove that the text encoder, VAEs and active tensors fit. |
| MiniMax H3 in ComfyUI | The guide describes multimodal references and native stereo audio, with version-specific T2V/I2V/R2V templates. Local open weights target about 768px short edge,24 fps and up to roughly 15 seconds; hosted2K output is separated from local upscaling. The guide requires a commercial license for commercial local outputs. [Comfy guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3), publication date unknown; retrieved 2026-11-01. | Local workflows exist in the source, but complete12 GB fit and generation time are unproven. Do not promise a local 15-second 2K clip. |
| FastH3 Preview v1 | Stored release supports text-to-video/audio only, not its future first/last/reference conditioning. The recommended sparse checkpoint requires the VSA-H3 backend/kernel. Its15-second 1344×768 24 fps example takes 47.2 seconds warm on one B200; loading/compilation are excluded. [FastVideo article](https://haoailab.com/blogs/fasth3-preview/), published 2026-08-27; retrieved 2026-11-01. | It misses the required image-conditioning feature for this version, and its B200 timing supplies no 12 GB GPU runtime guarantee. Future MLX/RTX optimization plans are not deployed compatibility. |
| MobileWan | The project derives a recurrently compressed model from Wan 2.2-5B and reports a5-second 480×832 16 fps clip in 20 seconds on a commercial mobile device. Exact device, precision and full memory are absent from that latency passage; the page links code/checkpoint/demo but also uses future release language. [Project page](https://qualcomm-ai-research.github.io/MobileWan/), publication date unknown; retrieved 2026-11-01. | Mobile generation and reduced attention memory do not establish this CUDA 12 GB configuration, image-conditioning support or commercial rights. |

The H3 package card additionally distinguishes diffusion INT8/convrot files from FP8 alternatives and a separate Qwen text encoder. Distribution variants need compatible software; the source does not permit replacing a whole-pipeline measurement with one file’s precision. [Packaging card](https://huggingface.co/Comfy-Org/MiniMax-H3), publication date unknown; retrieved 2026-11-01.

## Provisional choice and validation

**None of these four is verified to satisfy 12 GB. Validate a minimal LTX 2.5 distilled ComfyUI workflow first, conditional on its actual access/license and GPU/backend support.** This is a proposed bounded experiment based on documented configuration paths, not a speed/quality ranking. Reject FastH3 Preview v1 for the image-conditioned requirement unless a separately evidenced version changes that feature boundary.

1. Pin the actual GPU, driver/runtime, model components and workflow revision. Confirm gated access, intended-use terms and compatibility of the chosen quantization path. Expected result: all components and their required backends are identified before a large download. Observe separate text encoder/VAEs, optional upscalers and incompatible Comfy versus PyTorch assets.
2. Run the smallest documented supported image-conditioned clip, then the target settings. Measure process and GPU peak allocation, CPU offload, swapping, cold/warm duration and complete output properties. Expected result: the target job succeeds within 12 GB VRAM and a written time budget over repeated runs. Observe OOM, fallback, precision changes and whether host RAM is also sufficient. This brief has not run the experiment.
3. Review motion/identity, audio synchronization and prompt adherence at those exact settings. Expected result: artifacts meet the project acceptance criteria and commercial-use terms are resolved. Keep source versions, seed, failures and environment with the result; an output24/50 fps property must never be reported as render throughput.

## Evidence trail and manual diagnostic check

Curated records: `ltx-25`, `minimax-h3-comfy`, `fasth3-preview-v1`, `mobilewan`.

- LTX: source `92c1824269f45469ee06`, SHA `0d99f6d372b120168d7b4109cd751b040d3afde560986c453d2aef781ea4cd16`; lines16–37,55–89,117,158–164.
- H3 guide: source `044c0150f5408638bab0`, SHA `d959198a9557cf76b9a07389de3666a1ecdecdeb4c5d8cd693d2661dfee48d69`; lines15–41,48–49. Package: source `9e46d458613f25bfe688`, SHA `cccd9592752fd302f31e983d01efe375384fcf1af9fefaf24bae1ecc02ca77bb`; lines15–27,28–58.
- FastH3: source `435b2f544ed33453e535`, SHA `5dd7764f05206b76a5cb5d047948611bb5bb9f5a97fdab295b90efd3df597993`; lines77–90,350–373,549–556.
- MobileWan: source `cb1b3c8fb188a3d5ada7`, SHA `d71d04acd52c00a85cb3b0114ce0c00be98d6b7334729a8f6a17baf5bac06af3`; lines40–44,55–72,104–113,157–158.

Development fixture checks: `video-h3-mac-local` keeps present weight terms and target hardware/runtime/memory/time open; the later Comfy card supplies more local distribution evidence but still no 12 GB proof. `video-ltx-gated-download` requires actual access acceptance, and `video-ltx-fps-runtime` distinguishes output frame rate from rendering speed. `video-swift-memory-evidence` illustrates why hardware-specific timings cannot be relabeled; SwiftI2V is not added to this four-record candidate set. These are manual boundary checks against authored development cases, not universal or held-out AI accuracy scores.
