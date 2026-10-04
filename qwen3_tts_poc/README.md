# Qwen3-TTS CPU voice-cloning proof of concept

This folder is independent of the JARVIS Python environments. The environment,
Python runtime, package installs, model cache, reference file, and output WAV all
stay under this folder.

## Reference recording

Put your own permission-cleared recording at:

`qwen3_tts_poc\reference.wav`

Use a clear WAV recording. Provide the exact words spoken in that file with
`--ref-text`; do not paraphrase the transcript. The script's example transcript
is only a placeholder and must be replaced with the actual words.

## Run

From the JARVIS project folder in PowerShell:

```powershell
qwen3_tts_poc\.venv\Scripts\python.exe qwen3_tts_poc\benchmark_clone.py `
  --ref-text "Put the exact transcript of reference.wav here"
```

The default test sentence is `Hello. This is a short local voice cloning test.`
Override it with `--text "Your short English test sentence."`. Output defaults to
`qwen3_tts_poc\generated_test.wav`.

The first run downloads the public model/tokenizer files into
`qwen3_tts_poc\models\huggingface`; later runs reuse that local cache. After the
files are cached, add `--offline` to prevent model-file downloads. Inference is
CPU-only and no API or access token is used.

The benchmark prints model-load time, generation time, and sampled peak process
RAM. The API returns complete audio rather than a streaming first chunk, so
"time to first complete audio output" and total generation call time are the same.

## Environment

- Python 3.12.10 in `.python` (managed under this folder)
- Virtual environment in `.venv`
- `qwen-tts` 0.1.1
- CPU PyTorch and torchaudio; CUDA and FlashAttention 2 are not installed
- Gradio is omitted because this benchmark uses the Python API, not the web UI
