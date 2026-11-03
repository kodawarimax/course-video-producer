# 🎬 Course Video Producer v2.0

> **One-Command Deterministic Broadcast Course Video Generator for AI Coding Agents**  
> Supports **Claude Code**, **OpenAI Codex CLI**, **Google Antigravity**, and **Gemini 3.8 Flash / Gemini 4**.  
> Generates broadcast-grade 1080p 30fps BT.709 MP4 lecture videos with natural Japanese announcer narration (Fish Audio `s2-pro`), EBU R128 `-14.5 LUFS` 48kHz audio normalization, dual subtitles (burned-in + Japanese `mov_text` soft track), and auto-zooming textbook graphics.

---

## 🌟 Highlights (v2.0)

- **1-Command Zero-LLM Generation**: AI models do NOT write code, JSON, or scripts. One command parses textbook packages, synthesizes audio, renders full HD videos, and masters them to broadcast specs.
- **4-Stage Deterministic Scene Resolution**:
  1. Explicit `--scenes-json` path
  2. Package-local `<package_dir>/scenes_spec.json`
  3. Golden pre-validated specs in `examples/<course_id>_<lesson_id>_scenes_spec.json`
  4. Zero-LLM deterministic compiler from `batch.json` + `video-job.json` + `video-script.md` + `assets-manifest.json`
- **Natural Japanese Narration (`coji/natural-japanese` Integrated)**:
  - Built-in deterministic AI-cliché detector prevents translationese and unnatural LLM phrases while strictly preserving 100% of source textbook facts.
- **Unified Standard Voice (`ca8c24e05b1245c4bdbf28bfb9be5275`)**:
  - **Tone**: **プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー調）**
  - **Engine**: Fish Audio `s2-pro` (commercial-use friendly, copyright-free)
  - Sample audio included in `assets/sample_hybrid_1.mp3`.
- **Broadcast Mastering & 12/12 YouTube/LMS QC Pass (`kajisho5/ffmpeg-skill` Standard)**:
  - **Two-Pass Linear EBU R128 Loudness Normalization**: Targets `-14.5 LUFS` with `-1.5 dBTP` true-peak ceiling at `48000 Hz` `192kbps` stereo AAC (zero pumping, lossless video stream copy).
  - **BT.709 HD Color Space Tagging**: Stamps H.264 bitstream and MP4 container with `bt709/bt709` for identical color reproduction across QuickTime, Safari, Chrome, iOS, and YouTube.
  - **Dual Subtitles**: Combines broadcast-styled burned-in captions with a sentence-synchronized Japanese soft subtitle stream (`mov_text` / `language=jpn`).
- **Remotion Full-Image & Auto-Zoom (`remotion-dev/skills` & `remotion-video-director` Aligned)**:
  - Displays textbook diagrams and UI screenshots at 100% height, then smoothly zooms (`1.36x`) into spotlight coordinates.

---

## 📦 Directory Structure

```
course-video-producer/
├── SKILL.md                          # Agent skill definition (for Claude Code, Codex, Antigravity)
├── scripts/
│   └── render_course_package.py      # Core 1-command generator + EBU R128 / BT.709 / SRT mastering
├── examples/                         # Pre-validated golden scene specs (a01, a02, a03)
│   ├── lesson01_scenes_spec.json
│   ├── ai-user-a01_lesson01_scenes_spec.json
│   ├── ai-user-a02_lesson01_scenes_spec.json
│   ├── ai-user-a02_lesson02_scenes_spec.json
│   ├── ai-user-a03_lesson01_scenes_spec.json
│   └── ai-user-a03_lesson03_scenes_spec.json
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
- Python 3.10+
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
  --package-dir "/path/to/lesson_package" \
  --downloads-dir "$HOME/Downloads"
```

Outputs are automatically mastered, validated with `ffprobe`, and synced to:
- `<package_dir>/<job_folder>/<job_id>.mp4`
- `~/Downloads/<course_id>_<job_id>.mp4`
- `~/Downloads/<course_id>_videos/<job_id>.mp4`
- `~/Downloads/<course_id>_videos.zip`

---

## 📄 License
MIT License. Commercial use permitted.
