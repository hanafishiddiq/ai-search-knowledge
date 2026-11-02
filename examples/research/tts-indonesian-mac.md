# Research example: Indonesian narration on an Apple Silicon Mac

Prepared 2026-11-02 from source snapshots retrieved 2026-11-01. This is an original curator-authored worked example, with a provisional experiment choice. It is not a current availability guarantee, model benchmark, listening test or automatic agent answer.

## Constraints

Illustrative project: Indonesian narration with reference-voice cloning, local inference on an Apple Silicon Mac with 16 GB unified memory, and an eventual commercial output. Exact chip, acceptable generation time and narration quality threshold are not yet specified. A model must satisfy language, complete runtime memory, usable speed and applicable rights; a small parameter label alone cannot establish these.

## Candidates and evidence

| Candidate | What the retained evidence supports | What remains open for this project |
| --- | --- | --- |
| Audio8 TTS Realistic 0.6B | Indonesian is explicitly in the supported language list. The main model has 601,159,424 parameters excluding its codec. The card states Apache 2.0 for code and weights. Publisher runtime smoke uses NVIDIA H20 / BF16 with selected language cases, rather than a Mac. [Model card](https://huggingface.co/Edge0/Audio8-TTS-Realistic-0.6b), publication date unknown; retrieved 2026-11-01. | Apple Silicon runtime/backend, whole-stack peak memory, first-output time and narration quality on the intended Indonesian script. |
| Audio8 TTS Preview 0.1B | Main model is approximately 170M parameters plus a separate approximately 120M codec decoder. Chinese/English are primary. The linked ONNX package’s approximately 0.4 GiB after-load figure is specifically a tested Linux x86_64 setup. Model license is revenue-capped custom terms. [Preview card](https://huggingface.co/Edge0/Audio8-TTS-Preview-0.1b), publication date unknown; retrieved 2026-11-01. | Indonesian suitability and actual Mac memory/speed. The small CPU package is a separate deployment variant; its Linux figure cannot be substituted for a Mac measurement. |
| IndexTTS 2.5 | Listed languages are Chinese, English, Japanese, Spanish and Arabic. Instructions require NVIDIA hardware, Python 3.10–3.11 and roughly 6 GB VRAM, plus auxiliary downloads. [Model card](https://huggingface.co/IndexTeam/IndexTTS-2.5), publication date unknown; retrieved 2026-11-01. | Indonesian and Mac support are not established by this card. Its named bilibili model-use license needs intended-use review. |
| Higgs TTS 3 | Conversational speech controls, reference cloning, hosted/API paths and local downloadable weights are described. The article’s 100+ language positioning and macro benchmarks are broad evidence, rather than an Indonesian target-workload trial. [Boson article](https://www.boson.ai/blog/higgs-tts-3), published 2026-06-04; retrieved 2026-11-01. | Exact language-level fit, local hardware/runtime, complete memory and applicable weight terms. |

Audio8 Realistic reports Indonesian WER 13.743% and similarity 0.6682 on CV3. Its separate MiniMax table reports WER 2.128% and similarity 0.7270. These are different test sets and metric conditions; neither is a prediction for this narration script. Cross-project tables also use differing pipelines and size conventions. The archive provides evidence to investigate, without establishing a universal best voice.

## Provisional choice and validation

**Investigate Audio8 Realistic first; no candidate is yet qualified for production on this Mac.** It has the clearest retained evidence for both Indonesian and named code/weight terms. Preview’s smaller footprint does not offset the missing Indonesian evidence, and the H20 result does not settle Mac feasibility.

1. Check the actual current model/runtime artifacts and full component licenses, including the codec and attribution files; pin versions before installation. Expected result: a documented Apple Silicon inference path and an intended-use licensing checklist with no unresolved component. Observe unsupported backends, extra downloads and any different code/weights terms. Stop deployment work if these remain unresolved.
2. On an isolated local setup, use a permitted reference voice and a fixed Indonesian script containing names, numbers, abbreviations and natural pauses. Record whole-process peak unified memory, cold startup, time to first audio and total generation time. Expected result: reproducible files within a project-defined memory/time budget. Observe swapping, device fallback, utterance splitting and early stopping. No inference run was performed for this brief.
3. Have a fluent listener check pronunciation, omissions/repetition, delivery and voice consistency across repeated samples. Expected result: the project’s written acceptance criteria are met on the intended script. Compare another candidate only under matched reference/text/settings; retain failures and settings with the result.

## Evidence trail and manual diagnostic check

Curated record IDs: `audio8-tts-realistic-06b`, `audio8-tts-preview-01b`, `indextts-25`, `higgs-tts-3`.

- Audio8 Realistic: source `ca03e77e00827468345d`, full text SHA `191224e5efe4e871c6ebbec0dc8d83ff578788ca295839a17670885364bfebd6`; lines29–63,147–168,179–205,206–234,239–250.
- Preview: source `087337a222b159255808`, SHA `920fafdae5bab671a4fb01b56633badc8d9319a6ebebdb8b5c39612d4f77a02d`; lines24–26,40–76,174–184.
- IndexTTS: source `a299aa1bde23bcdfc7d9`, SHA `d3b4f345c6b8cfe6c1826817266475609809b535883800dd3db0c0aca8ade494`; lines18–34,48–49.
- Higgs: source `56b2c8931c56b7a19b7c`, SHA `e8ae897906dae158780c187fd9165fdefda0cc329114f3d17e75a74c7ce606dd`; lines19–39,58–65,81–93.

Manual comparison with development fixture cases `tts-wav-indonesian-commercial`, `tts-audio8-size`, `tts-audio8-indonesian-evaluation`, `tts-audio8-streaming-throughput` and `tts-audio8-higgs-ranking`: Indonesian target-workload evaluation and applicable commercial terms stay open until checked; codec count, differing benchmark suites and unmeasured streaming speed remain distinct. The WavTTS fixture contributes its expected-unknown rule, not a fifth candidate recommendation. This is a boundary review of one authored example, not a scored or independent answer-quality benchmark.
