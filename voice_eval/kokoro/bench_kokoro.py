"""Isolated Kokoro-82M CPU benchmark (JARVIS' current local engine) - measured, no cloning.

Run with voice_eval/kokoro/.venv. Measures true time-to-first-audio-chunk because
KPipeline yields audio incrementally per sentence/segment.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("HF_HOME", str(HERE / "hf_home"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
import evalkit  # noqa: E402

SAMPLE_RATE = 24000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", nargs="+", default=["a:af_heart", "b:bm_george", "b:bm_lewis"],
                    help="lang_code:voice pairs ('a'=American, 'b'=British)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"

    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KPipeline

    print(f"Torch {torch.__version__}, threads={torch.get_num_threads()}, cuda={torch.cuda.is_available()}", flush=True)
    out_dir = HERE / "out"
    out_dir.mkdir(exist_ok=True)
    results = {"engine": "Kokoro-82M", "device": "cpu", "streaming_supported": True, "voices": {}}

    pipelines: dict[str, KPipeline] = {}
    with evalkit.ResourceSampler() as load_stats:
        t0 = time.perf_counter()
        for spec in args.voices:
            lang, _ = spec.split(":")
            if lang not in pipelines:
                pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        load_s = time.perf_counter() - t0
    results["model_load"] = {"seconds": round(load_s, 2), **load_stats.summary()}
    print(f"Pipeline load: {load_s:.2f} s, peak RAM {load_stats.summary()['peak_rss_gib']} GiB", flush=True)

    for spec in args.voices:
        lang, voice = spec.split(":")
        pipe = pipelines[lang]
        vres = {}
        for name, sentence in evalkit.SENTENCE_SUITE.items():
            runs = []
            for run in range(1, args.runs + 1):
                chunks, first = [], None
                with evalkit.ResourceSampler() as stats:
                    t0 = time.perf_counter()
                    for _, _, audio in pipe(sentence, voice=voice):
                        if first is None:
                            first = time.perf_counter() - t0
                        chunks.append(audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio))
                    total = time.perf_counter() - t0
                wav = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
                dur = len(wav) / SAMPLE_RATE
                wav_path = out_dir / f"{voice}_{name}.wav"
                if run == args.runs:
                    sf.write(str(wav_path), wav, SAMPLE_RATE)
                runs.append({"run": run, "first_audio_s": round(first or total, 3), "total_s": round(total, 3),
                             "audio_s": round(dur, 2), "rtf": round(evalkit.rtf(total, dur), 3), **stats.summary()})
            vres[name] = {"text": sentence, "runs": runs,
                          "integrity": evalkit.audio_integrity(wav, SAMPLE_RATE, wav_path), "wav": str(wav_path)}
            w = runs[-1]
            print(f"[{voice:12s}] {name:8s} first={w['first_audio_s']:.3f}s total={w['total_s']:.3f}s "
                  f"audio={w['audio_s']:.2f}s RTF={w['rtf']:.3f} RAM={w['peak_rss_gib']}GiB "
                  f"CPU={w['cpu_avg_pct_of_one_core']:.0f}%", flush=True)
        results["voices"][voice] = vres

    results["peak_rss_gib_overall"] = max(
        [results["model_load"]["peak_rss_gib"]]
        + [r["peak_rss_gib"] for v in results["voices"].values() for s in v.values() for r in s["runs"]])
    evalkit.write_json(HERE / "kokoro_result.json", results)
    print("Peak RAM overall:", results["peak_rss_gib_overall"], "GiB; JSON:", HERE / "kokoro_result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
