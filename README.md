# 🎬 Course Video Producer v3.0

> **One-command, deterministic narrated-video generator for AI coding agents**
> (Claude Code / Codex CLI / Antigravity / Gemini).
> Turns a lesson package **or any document — Markdown, PDF, PowerPoint, Word, HTML, or a web URL —**
> into a broadcast-grade MP4 in **16:9, 9:16 (Shorts/Reels) or 1:1**, with natural Japanese narration,
> brand themes, embedded screen-recording clips, EBU R128 loudness, BT.709 tags and Japanese soft subtitles.

---

## 🌟 What's new in v3.0

| Area | v2.0 | v3.0 |
| :--- | :--- | :--- |
| **Input** | `batch.json` + `scenes_spec.json` package only | `--input` accepts `.md/.txt/.pdf/.pptx/.ppt/.key/.docx/.html` and `http(s)` URLs |
| **Format** | 16:9 only, single navy palette, still images only | `--aspect 16:9/9:16/1:1`, `--theme` (5 presets), `video-clip` scenes (`<OffthreadVideo>`) |
| **Portability** | Fish Audio + macOS Keychain only, hard-coded `/Users/...` paths | `--tts auto/fish/edge/say`, env-var configuration, Keychain only on macOS, no absolute paths |
| **Sync** | per-scene rounding drift (up to ~33 ms/scene) | each scene's audio padded to its exact frame length |
| **Bugfix** | `verify_mp4` referenced undefined `WIDTH/HEIGHT` | expected size passed explicitly |

### Open-source building blocks combined

- [microsoft/markitdown](https://github.com/microsoft/markitdown) — DOCX / PPTX (speaker notes) / HTML / URL → Markdown
- [poppler](https://poppler.freedesktop.org/) `pdftoppm` / `pdftotext` — PDF page images + page text
- LibreOffice headless — PPTX/PPT/Keynote → PDF
- [rany2/edge-tts](https://github.com/rany2/edge-tts) and macOS `say` — key-less TTS fallback
- [remotion-dev/skills](https://github.com/remotion-dev/skills) patterns — `calculateMetadata` dynamic canvas, `<OffthreadVideo>`, `<Freeze>`
- [kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) delivery spec — EBU R128 / BT.709 / subtitle checks
- [coji/natural-japanese](https://github.com/coji/natural-japanese) — AI-cliché detection (warn only, source text never rewritten)

---

## 📦 Directory Structure

```
course-video-producer/
├── SKILL.md                          # Agent skill definition
├── scripts/
│   ├── render_course_package.py      # 1-command renderer + mastering
│   └── compile_input_to_spec.py      # Universal input -> package compiler (v3.0)
├── examples/                         # Pre-validated golden scene specs
├── assets/sample_hybrid_1.mp3        # Standard voice preview
└── remotion/src/scenes/lesson01/Lesson01Video.tsx   # 11 layouts, 3 aspects, 5 themes
```

---

## 🚀 Quick Start

### Requirements
- Node.js 18+, Python 3.9+, FFmpeg
- Optional by input type: poppler (PDF), LibreOffice (PPTX), `pip install 'markitdown[all]'` (DOCX/HTML/URL/PPTX notes)
- TTS: Fish Audio API key (standard voice) **or** `pip install edge-tts` **or** macOS

```bash
git clone https://github.com/kodawarimax/course-video-producer.git
cd course-video-producer/remotion && npm install && cd ..
export FISHAUDIO_API_KEY="..."   # optional; macOS Keychain 'FishAudio' also works
```

### Any document → video
```bash
python3 scripts/render_course_package.py --input guide.md
python3 scripts/render_course_package.py --input deck.pptx --aspect 9:16 --theme sakura
python3 scripts/render_course_package.py --input report.pdf --aspect 1:1 --tts edge
python3 scripts/render_course_package.py --input https://example.com/article
```

### Existing lesson package → video
```bash
python3 scripts/render_course_package.py --package-dir "/path/to/lesson_package"
```

### Markdown conventions
```markdown
# Video title                      <- title scene
## Section heading                 <- one scene per ## / ###
Paragraph text becomes narration.
- bullets become on-screen points
| tables | become | table scenes |
![](screen.png)                    <- full-image / split-image / dual-image
![](demo.mp4)                      <- video-clip scene (muted, synced to narration)
<!-- narration: override the spoken text for this section -->
```

### Environment variables
| Variable | Default |
| :--- | :--- |
| `COURSE_VIDEO_REMOTION_ROOT` | bundled `remotion/` (if npm-installed), else `~/Claude/content/video` |
| `COURSE_VIDEO_DOWNLOADS_DIR` | `~/Downloads` (`--downloads-dir ""` disables copying) |
| `COURSE_VIDEO_EDGE_VOICE` | `ja-JP-NanamiNeural` |
| `COURSE_VIDEO_SAY_VOICE` | `Kyoko` |

---

## ⚠️ Known limitations
- Image-only PDFs (no text layer) produce heading-only narration; no OCR is performed.
- Slide/page text is often fragmentary; PPTX speaker notes give much better narration.
- 9:16 / 1:1 scale the 16:9 stage to canvas width, so in-stage small text is hard to read on phones
  (compensated by a large title band, large key points and large subtitles).
- `edge` TTS sends narration text to Microsoft's online service.
- Subtitle timing is proportional to character count (can drift up to ~1 s within long scenes).

## 📄 License
MIT License. Commercial use permitted.
