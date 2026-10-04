"""Local CPU proof-of-concept benchmark for Qwen3-TTS 0.6B Base voice cloning."""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

POC_DIR = Path(__file__).resolve().parent

# Put your permission-cleared WAV at qwen3_tts_poc/reference.wav.
DEFAULT_REFERENCE_WAV = POC_DIR / "reference.wav"

# Supply the exact spoken words in --ref-text. Do not paraphrase or normalize them.
# Example only: "Good morning. The train leaves at nine o'clock."

# This is the short English sentence used unless --text overrides it.
DEFAULT_TEST_SENTENCE = "Hello. This is a short local voice cloning test."
DEFAULT_OUTPUT_WAV = POC_DIR / "generated_test.wav"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"

# Keep all Hugging Face model/tokenizer downloads and caches inside this POC folder.
os.environ.setdefault("HF_HOME", str(POC_DIR / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class PeakRssSampler:
    """Sample this process' resident memory while model loading/generation runs."""

    def __init__(self) -> None:
        import psutil

        self.process = psutil.Process(os.getpid())
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, self.process.memory_info().rss)
            except Exception:
                pass
            self._stop.wait(0.2)

    def __enter__(self) -> "PeakRssSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def peak_gib(self) -> float:
        return self.peak / (1024**3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref-audio", type=Path, default=DEFAULT_REFERENCE_WAV,
                        help="Local reference WAV (default: qwen3_tts_poc/reference.wav)")
    parser.add_argument("--ref-text",
                        help="Exact transcript of the reference WAV")
    parser.add_argument("--text", default=DEFAULT_TEST_SENTENCE,
                        help="Short English sentence to generate")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_WAV,
                        help="Output WAV path")
    parser.add_argument("--offline", action="store_true",
                        help="Require model files to already be cached locally")
    parser.add_argument("--load-only", action="store_true",
                        help="Load and benchmark the model without requiring a reference WAV")
    args = parser.parse_args()

    if not args.load_only and not args.ref_audio.is_file():
        parser.error(
            f"reference WAV not found: {args.ref_audio}\n"
            "Place your permission-cleared recording at qwen3_tts_poc/reference.wav "
            "or pass --ref-audio."
        )
    if not args.load_only and (not args.ref_text or not args.ref_text.strip()):
        parser.error("--ref-text must contain the exact words spoken in the reference WAV")

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    if torch.cuda.is_available():
        raise RuntimeError("CUDA is unexpectedly available; this benchmark is configured for CPU only")

    # Explicit CPU/float32/SDPA settings avoid CUDA, FlashAttention, and GPU assumptions.
    print(f"Loading {MODEL_ID} on CPU (float32, SDPA)...", flush=True)
    load_started = time.perf_counter()
    with PeakRssSampler() as load_memory:
        model = Qwen3TTSModel.from_pretrained(
            MODEL_ID,
            device_map="cpu",
            dtype=torch.float32,
            attn_implementation="sdpa",
            local_files_only=args.offline,
        )
    load_seconds = time.perf_counter() - load_started
    print(f"Model load time: {load_seconds:.2f} s", flush=True)
    print(f"Peak process RAM during load: {load_memory.peak_gib:.2f} GiB", flush=True)

    if args.load_only:
        print("Load-only run complete; voice generation requires your reference WAV and exact transcript.")
        return 0

    print("Generating audio...", flush=True)
    generation_started = time.perf_counter()
    with PeakRssSampler() as generation_memory:
        wavs, sample_rate = model.generate_voice_clone(
            text=args.text,
            language="English",
            ref_audio=str(args.ref_audio.resolve()),
            ref_text=args.ref_text,
        )
    generation_seconds = time.perf_counter() - generation_started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), wavs[0], sample_rate)

    print(f"Time to first complete audio output: {generation_seconds:.2f} s")
    print(f"Total generation call time: {generation_seconds:.2f} s")
    print(f"Peak process RAM during generation: {generation_memory.peak_gib:.2f} GiB")
    print(f"Output WAV: {args.output.resolve()}")
    print(f"Audio: {len(wavs[0]) / sample_rate:.2f} s at {sample_rate} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
