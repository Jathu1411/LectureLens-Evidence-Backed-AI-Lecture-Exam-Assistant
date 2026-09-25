# AGENTS.md

## Project context
A local, offline pipeline that converts a 3-hour recorded lecture video (screen + audio)
into a PDF study guide with key points and a summary. Runs entirely on the local
machine — no cloud APIs, no external LLM calls. Uses local Whisper for transcription
and a local Llama model (via Ollama) for summarization.

## Architecture (do not deviate without discussion)
1. **Ingestion** — ffmpeg extracts audio and samples video frames.
2. **Slide detection** — frame-diff (SSIM/perceptual hash) on sampled frames to find
   slide-change points; only keep one frame per distinct slide.
3. **Audio path** — faster-whisper (large-v3 on GPU, medium on CPU) transcribes audio
   into timestamped segments. Always pass `language="en"` explicitly, never rely on
   auto-detect. Use `vad_filter=True`.
4. **Visual path** — OCR (Tesseract) on detected slide frames; fall back to a local
   vision-LLM (via Ollama) only if plain OCR output looks unreliable (e.g. equations,
   diagrams, handwriting).
5. **Alignment** — merge audio segments and slide text into one ordered timeline keyed
   by video timestamp.
6. **Summarization** — map-reduce over the aligned timeline using a local Llama model
   through Ollama's local HTTP API (`http://localhost:11434`). Chunk by ~10-15 minute
   segments (prefer slide boundaries over arbitrary word counts). Map step summarizes
   each chunk; reduce step combines chunk summaries into the final structured guide.
7. **Output** — render the final structured summary (overview, key points, summary)
   into a PDF via WeasyPrint (HTML → PDF template).

## Tech stack
- Python 3.x for all pipeline/orchestration code
- ffmpeg (system dependency, not a Python package)
- faster-whisper for transcription
- OpenCV (`opencv-python`) for frame extraction and slide-change detection
- pytesseract (Tesseract OCR) for slide text
- Ollama (local server) running a local Llama model for summarization
- WeasyPrint for PDF generation
- PostgreSQL (local instance) for storing intermediate pipeline state (segments,
  slide timestamps, chunk summaries) so a crash mid-run doesn't lose earlier progress.
  Use `psycopg` (or `psycopg2`) for the Python connection. JSONB columns are fine for
  flexible chunk metadata (e.g. per-chunk summary drafts).

## Coding standards
- Write clean, readable Python with clear variable names — prefer straightforward
  logic over clever one-liners.
- Every long-running stage (transcription, OCR, summarization) should write its
  output incrementally to Postgres as it progresses, not just at the very end —
  this pipeline processes hour-plus files and must be resumable.
- No cloud API calls anywhere in this project. Everything must run locally
  (Whisper, OCR, and the LLM are all local). Flag it clearly if a suggested library
  would require an external network call.
- Keep pipeline stages as separate, independently runnable scripts/functions
  (ingestion, transcription, OCR, alignment, summarization, PDF export) rather than
  one monolithic script — this makes it easy to re-run a single failed stage instead
  of the whole 3-hour pipeline.

## Constraints
- Do not swap in a cloud-hosted LLM or ASR API without being asked — the entire point
  of this project is a fully local/offline pipeline.
- Do not process every video frame through OCR — always run slide-change detection
  first to cut down the number of frames actually OCR'd.
- Assume long-running inputs (3+ hour videos) by default; avoid patterns that load
  entire files fully into memory when a streaming/generator approach is available.
