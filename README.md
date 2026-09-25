# Lecture Video to Study Guide Pipeline

A local, offline, multimodal pipeline that converts a 3-hour recorded lecture video (screen capture + spoken audio) into a publication-grade PDF study guide with key takeaways, section-by-section lecture notes, and visual slide references.

> **Zero Cloud APIs • 100% Offline • Local Whisper & Local Llama via Ollama • Resumable Database Checkpoints**

---

## 📖 Complete Documentation

For the full architectural deep dive, component specifications, problem/solution analysis, database schemas, and data flow diagrams, see:
👉 **[ARCHITECTURE.md](file:///Users/jathu/Documents/Lecture%20notes%20guide/ARCHITECTURE.md)**

---

## 🚀 Quick Start

### 1. Prerequisites
* **Python 3.10+**
* **FFmpeg** & **Tesseract OCR**
* **Ollama** installed with models:
  ```bash
  ollama pull llama3
  ollama pull llama3.2-vision
  ```
* **PostgreSQL** (Optional; automatically falls back to SQLite if PostgreSQL is not running)

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Generate a Demo Lecture (Optional)
```bash
python scripts/create_demo_lecture.py
```

### 4. Run the Pipeline
```bash
# 1. Open native laptop file picker & run windowed pipeline:
python main.py process

# Or browse & inspect a video file first:
python main.py pick

# Or pass a path directly:
python main.py process sample_data/demo_lecture.mp4 --run-id demo_01

# Inspect run status
python main.py status demo_01
```

### 5. Web Interface (Next.js)
```bash
cd web
npm install
npm run dev
# Visit http://localhost:3000
```
