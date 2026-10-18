# 🎬 Course Video Producer

> **One-Command Deterministic Course Video Generator for AI Coding Agents**  
> Supports **Claude Code**, **OpenAI Codex CLI**, **Google Antigravity**, and **Gemini 3.8 Flash / Gemini 4**.  
> Generates broadcast-grade 1080p 30fps MP4 lecture videos with commercial-friendly Japanese AI voice narration and auto-zooming textbook graphics.

---

## 🌟 Highlights

- **1-Command Zero-LLM Generation**: AI models do NOT write code, JSON, or scripts. One command parses textbook packages, synthesizes audio, and renders full HD videos.
- **Zero Hallucination Guarantee**: Automatic compiler reads `batch.json`, `video-job.json`, `video-script.md`, and `assets-manifest.json` with 100% textbook fidelity (exact tables, designated opening lines, verbatim prompt examples).
- **Unified Standard Voice (`ca8c24e05b1245c4bdbf28bfb9be5275`)**:
  - **Tone**: **プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー調）**
  - **Engine**: Fish Audio `s2-pro` (commercial-use friendly, copyright-free)
  - Sample audio included in `assets/sample_hybrid_1.mp3`.
- **4-Worker Parallel TTS + SHA-256 Audio Cache**: Synthesizes 15–20 scenes in parallel in seconds; unchanged scenes are instantly reused.
- **Remotion Full-Image & Auto-Zoom**: Displays textbook diagrams and UI screenshots at 100% height, then automatically smoothly zooms (1.36x) into spotlight coordinates.

---

## 📦 Directory Structure

```
course-video-producer/
├── SKILL.md                          # Agent skill definition (for Claude Code, Codex, Antigravity)
├── scripts/
│   └── render_course_package.py      # Core 1-command generator
├── examples/
│   └── lesson01_scenes_spec.json     # Pre-validated golden scene spec
├── assets/
│   └── sample_hybrid_1.mp3           # Sample voice preview
├── remotion/                         # Remotion React video templates
│   ├── package.json
│   ├── src/
│   │   ├── Root.tsx
│   │   ├── index.ts
│   │   └── scenes/lesson01/Lesson01Video.tsx
└── README.md
```

---

## 🚀 Quick Start

### 1. Requirements
- Node.js 18+ & npm
- Python 3.9+
- FFmpeg (`brew install ffmpeg`)
- Fish Audio API Key ([fish.audio](https://fish.audio))

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/kodawarimax/course-video-producer.git
cd course-video-producer

# Install Remotion dependencies
cd remotion && npm install && cd ..

# Set your Fish Audio API Key (or store in macOS Keychain under 'FishAudio')
export FISHAUDIO_API_KEY="your_api_key_here"
```

### 3. Generate Videos in 1 Command
```bash
python3 scripts/render_course_package.py \
  --package-dir "/path/to/lesson_package"
```

Outputs are automatically validated with `ffprobe` and synced to:
- `<package_dir>/<job_folder>/<job_id>.mp4`
- `~/Downloads/<job_id>.mp4`
- `~/Downloads/<package_name>_videos.zip`

---

## 🎙️ Voice Profiles & Customization

The pipeline defaults to:
- **Reference ID**: `ca8c24e05b1245c4bdbf28bfb9be5275`
- **Model**: `s2-pro`
- **Prosody**: `speed: 0.98`, `volume: 0`, `top_p: 0.8`, `temperature: 0.75`

To specify a different voice ID:
```bash
python3 scripts/render_course_package.py \
  --package-dir "/path/to/lesson_package" \
  --voice-id "<custom_voice_id>"
```

---

## 🤖 Using as an AI Agent Skill

### Claude Code / Codex / Antigravity
Add this directory to your skills path or symlink it:
```bash
ln -s "$(pwd)" ~/.claude/skills/course-video-producer
# or
ln -s "$(pwd)" ~/.agents/skills/course-video-producer
```

When you instruct any AI agent (even lower-tier models like Gemini 3.8 Flash):
> *"Please produce course videos from `/path/to/lesson01`"*

The agent reads `SKILL.md` and executes `render_course_package.py` in a single turn without hallucinating code or layouts.

---

## 📄 License
MIT License. Commercial use permitted.
