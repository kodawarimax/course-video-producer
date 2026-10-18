#!/usr/bin/env python3
"""
One-Command Deterministic Course Video Producer Pipeline (TokenZero / Formula-First)
Designed so even lower-tier AI models (Gemini 3.8 Flash Low/Medium, Haiku, etc.) can
generate 100% textbook-faithful, broadcast-grade 1080p MP4 videos in a single command:

  python3 /Users/jungosakamoto/Claude/ai-ops/master_skills/content/course-video-producer/scripts/render_course_package.py \
    --package-dir "/Users/jungosakamoto/Downloads/lesson01 2"

Key Features:
1. Zero-LLM Auto-Compilation:
   - If `--scenes-json` is omitted, automatically checks `examples/<lesson_id>_scenes_spec.json`
     or deterministically compiles `video-job.json` + `video-script.md` + `assets-manifest.json`
     into Remotion scene specs without LLM token generation or hallucination risk.
2. Unified Default Voice (`ca8c24e05b1245c4bdbf28bfb9be5275`):
   - "プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー）" via Fish Audio `s2-pro`.
3. Parallel TTS Synthesis (`ThreadPoolExecutor(max_workers=4)`):
   - Synthesizes scene audio concurrently with SHA-256 content+voice caching (3-4x faster).
4. Full-Screen & Auto-Zoom Layout Compliance:
   - Preserves 100% image display (`full-image` / `spotlights` auto-zoom) and exact textbook tables.
5. Strict Mux & Verification:
   - Renders 1920x1080 30fps via Remotion, muxes with `ffmpeg -map 0:v:0 -map 1:a:0`,
     verifies via `ffprobe`, and syncs outputs to the package folder, Downloads, and ZIP archive.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_REMOTION = SKILL_ROOT / "remotion"
REMOTION_ROOT = REPO_REMOTION if (REPO_REMOTION / "package.json").exists() else Path("/Users/jungosakamoto/Claude/content/video")
PUBLIC_DIR = REMOTION_ROOT / "public"
SCENES_OUT_DIR = REMOTION_ROOT / "src" / "scenes" / "lesson01"

# Unified Default Voice: sample_hybrid_1.mp3
# 「プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー）」(Fish Audio s2-pro / 商用・著作権フリー)
DEFAULT_VOICE_ID = "ca8c24e05b1245c4bdbf28bfb9be5275"
DEFAULT_MODEL = "s2-pro"
FPS = 30
GAP_SEC = 0.45

# Only replace ASCII/English acronyms that TTS might spell letter-by-letter.
# NEVER convert standard Japanese Kanji or strip 「」 into spaces, as doing so
# destroys Fish Audio s2-pro's LLM context and pitch-accent phrase boundaries.
S2_PRO_SAFE_REPLACEMENTS = [
    ("Googleアカウント", "グーグルアカウント"),
    ("Google Chrome", "グーグルクローム"),
    ("Google", "グーグル"),
    ("ChatGPT", "チャットジーピーティー"),
    ("Anthropic", "アンソロピック"),
    ("Claude", "クロード"),
    ("Gemini", "ジェミニ"),
    ("あなたのdot", "あなたのドット"),
    ("dot", "ドット"),
    ("A1", "エーワン"),
    ("A2", "エーツー"),
    ("500MB", "500メガバイト"),
    ("200MB", "200メガバイト"),
    ("URL", "ユーアールエル"),
    ("PDF", "ピーディーエフ"),
    ("SNS", "エスエヌエス"),
    ("Web", "ウェブ"),
    ("FAQ", "エフエーキュー"),
    ("OK", "オッケー"),
    ("NG", "エヌジー"),
    ("AI", "エーアイ"),
    ("1〜2行", "1から2行"),
    ("2〜3個", "2から3個"),
    ("2〜3日", "2から3日"),
    ("1〜3個", "1から3個"),
    ("①", "1番の、"),
    ("②", "2番の、"),
    ("③", "3番の、"),
    ("④", "4番の、"),
    ("⑤", "5番の、"),
    ("⑥", "6番の、"),
]


def get_fish_api_key() -> str:
    env_key = (
        os.environ.get("FISHAUDIO_API_KEY")
        or os.environ.get("FISH_AUDIO_API_KEY")
        or os.environ.get("FISH_API_KEY")
    )
    if env_key and len(env_key.strip()) > 20:
        return env_key.strip()
    for cmd in (
        ["security", "find-generic-password", "-s", "FishAudio", "-w"],
        ["security", "find-generic-password", "-s", "FISHAUDIO_API_KEY", "-w"],
        ["security", "find-generic-password", "-s", "fish-audio-api-key", "-w"],
    ):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and len(res.stdout.strip()) > 20:
            return res.stdout.strip()
    raise RuntimeError(
        "FishAudio API key not found in environment or macOS Keychain ('FishAudio')."
    )


def normalize_for_s2_pro(text: str) -> str:
    t = text.strip()
    for k, v in S2_PRO_SAFE_REPLACEMENTS:
        t = t.replace(k, v)
    t = re.sub(r"[ \t]+", " ", t)
    return t


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def verify_mp4(path: Path) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    info = json.loads(out)
    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not (has_video and has_audio):
        raise RuntimeError(
            f"Verification failed for {path}: video={has_video}, audio={has_audio}"
        )
    return info


def synthesize_tts(
    text: str,
    out_mp3: Path,
    api_key: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model: str = DEFAULT_MODEL,
) -> float:
    spoken_text = normalize_for_s2_pro(text)
    payload_dict = {
        "text": spoken_text,
        "reference_id": voice_id,
        "format": "mp3",
        "mp3_bitrate": 192,
        "normalize": True,
        "latency": "normal",
        "prosody": {"speed": 0.98, "volume": 0},
        "top_p": 0.8,
        "temperature": 0.75,
        "chunk_length": 260,
    }
    sig = hashlib.sha256(
        json.dumps(
            {"model": model, **payload_dict}, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()[:16]
    meta_file = out_mp3.with_suffix(f".{sig}.ok")

    if out_mp3.exists() and out_mp3.stat().st_size > 1000 and meta_file.exists():
        return ffprobe_duration(out_mp3)

    for old_ok in out_mp3.parent.glob(f"{out_mp3.stem}.*.ok"):
        old_ok.unlink(missing_ok=True)

    raw_mp3 = out_mp3.with_suffix(f".{sig}.raw.mp3")
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts",
        data=json.dumps(payload_dict).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": model,
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw_mp3.write_bytes(resp.read())

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_mp3),
            "-af",
            f"silenceremove=start_periods=1:start_silence=0.08:start_threshold=-52dB,apad=pad_dur={GAP_SEC}",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    raw_mp3.unlink(missing_ok=True)
    meta_file.write_text(spoken_text, encoding="utf-8")
    return ffprobe_duration(out_mp3)


def sync_package_images(package_dir: Path, lesson_id: str) -> Path:
    src_images = package_dir / "images"
    dst_images = PUBLIC_DIR / lesson_id / "images"
    dst_images.mkdir(parents=True, exist_ok=True)
    if src_images.exists():
        for img in src_images.iterdir():
            if img.is_file():
                target = dst_images / img.name
                shutil.copy2(img, target)
                os.chmod(target, 0o644)
        subprocess.run(["xattr", "-cr", str(dst_images)], check=False)
    return dst_images


def concat_mp3_files(mp3_files: list[Path], out_mp3: Path) -> None:
    list_file = out_mp3.with_suffix(".concat.txt")
    lines = [f"file '{p.resolve()}'" for p in mp3_files]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    list_file.unlink(missing_ok=True)


def _parse_markdown_sections(md_text: str) -> dict[str, dict]:
    """
    Deterministically extracts Markdown tables, bullet points, and callouts per section number
    from `video-script.md` so any new lesson package can be compiled without LLM guesswork.
    """
    result: dict[str, dict] = {}
    blocks = re.split(r"(?m)^###\s+(\d+)\.\s+(.+)$", md_text)
    # blocks[0] is preamble, then (num, title, body) triplets
    for i in range(1, len(blocks) - 2, 3):
        sec_num = int(blocks[i])
        sec_id_suffix = f"section{sec_num:02d}"
        body = blocks[i + 2]

        # Extract markdown table if any
        table_lines = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip().startswith("|") and ln.strip().endswith("|")
        ]
        headers: list[str] = []
        rows: list[list[str]] = []
        if len(table_lines) >= 3:
            headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
            for rline in table_lines[2:]:
                if set(rline.replace("|", "").strip()) <= {"-", ":", " "}:
                    continue
                rows.append([c.strip() for c in rline.strip("|").split("|")])

        # Extract bullet items
        bullets = [
            re.sub(r"^[-*]\s+", "", ln.strip())
            for ln in body.splitlines()
            if re.match(r"^\s*[-*]\s+[^|]", ln)
        ]

        # Extract numbered items
        numbered = [
            re.sub(r"^\d+\.\s+", "", ln.strip())
            for ln in body.splitlines()
            if re.match(r"^\s*\d+\.\s+", ln)
        ]

        result[sec_id_suffix] = {
            "headers": headers,
            "rows": rows,
            "bullets": bullets[:6],
            "numbered": numbered[:6],
        }
    return result


def auto_compile_package_to_scenes(package_dir: Path) -> dict:
    """
    Zero-LLM deterministic compiler from `<package_dir>/batch.json` + `<job>/video-job.json`
    + `<job>/video-script.md` into the exact `scenes_spec.json` schema consumed by Remotion.
    """
    batch_data = json.loads((package_dir / "batch.json").read_text(encoding="utf-8"))
    lesson_id = batch_data.get("lessonId") or batch_data.get("lesson_id", "lesson01")
    lesson_title = batch_data.get("lessonTitle") or batch_data.get("lesson_title", "")
    jobs_out: dict[str, dict] = {}

    badge_colors = ["blue", "teal", "purple", "amber", "green"]

    for job_entry in batch_data.get("jobs", []):
        job_id = job_entry.get("jobId") or job_entry.get("id")
        folder = job_entry.get("folder", job_id)
        job_dir = package_dir / folder
        vjob = json.loads((job_dir / "video-job.json").read_text(encoding="utf-8"))
        md_path = job_dir / "video-script.md"
        md_sections = (
            _parse_markdown_sections(md_path.read_text(encoding="utf-8"))
            if md_path.exists()
            else {}
        )

        pdf_spec = vjob.get("pdf_spec", {})
        opening = (pdf_spec.get("opening") or "").strip()
        scenario_sections = pdf_spec.get("scenario_sections", [])
        scenes: list[dict] = []

        for idx, sec in enumerate(scenario_sections):
            sec_id = sec.get("id", f"{lesson_id}-section{idx+1:02d}")
            sec_suffix = sec_id.split("-")[-1]
            title = sec.get("title", "")
            nar_lines = [ln.strip() for ln in sec.get("narration_source", []) if ln.strip()]
            images = sec.get("images", [])
            prod_note = (sec.get("production_note") or "") + " " + (sec.get("display_note") or "")
            md_info = md_sections.get(sec_suffix, {})

            narration = "。".join(
                ln.rstrip("。") for ln in nar_lines if len(ln.strip()) > 1
            )
            if narration and not narration.endswith("。"):
                narration += "。"
            if idx == 0 and opening and opening not in narration:
                narration = f"{opening}。{narration}"

            sub_text = nar_lines[0] if nar_lines else title
            tip_text = nar_lines[-1] if len(nar_lines) > 1 else ""
            color = badge_colors[idx % len(badge_colors)]
            sec_num_match = re.search(r"(\d+)$", sec_id)
            sec_num_str = sec_num_match.group(1) if sec_num_match else f"{idx+1:02d}"

            scene_obj: dict = {
                "id": f"{job_id}-{sec_suffix}",
                "sectionId": sec_id,
                "sectionLabel": f"{int(sec_num_str):02d}. {title}",
                "badge": f"SECTION {int(sec_num_str):02d}",
                "badgeColor": color,
                "heading": title,
                "sub": sub_text,
                "tip": tip_text,
                "narration": narration,
            }

            if md_info.get("headers") and md_info.get("rows"):
                scene_obj["kind"] = "table"
                scene_obj["tableHeaders"] = md_info["headers"]
                scene_obj["tableRows"] = md_info["rows"]
                if images:
                    scene_obj["image"] = f"images/{images[0]['filename']}"
                    scene_obj["imageCaption"] = images[0].get("caption") or images[0].get("alt", "")
            elif len(images) == 2:
                scene_obj["kind"] = "dual-image"
                scene_obj["image"] = f"images/{images[0]['filename']}"
                scene_obj["imageCaption"] = images[0].get("caption") or images[0].get("alt", "")
                scene_obj["secondImage"] = f"images/{images[1]['filename']}"
                scene_obj["secondImageCaption"] = images[1].get("caption") or images[1].get("alt", "")
            elif len(images) >= 1 and ("100%" in prod_note or "操作画面" in prod_note):
                scene_obj["kind"] = "full-image"
                scene_obj["image"] = f"images/{images[0]['filename']}"
                scene_obj["imageCaption"] = images[0].get("caption") or images[0].get("alt", "")
            elif len(images) >= 1:
                scene_obj["kind"] = "split-image"
                scene_obj["image"] = f"images/{images[0]['filename']}"
                scene_obj["imageCaption"] = images[0].get("caption") or images[0].get("alt", "")
                bullets = md_info.get("bullets") or nar_lines[1:4]
                scene_obj["cards"] = [
                    {"title": f"ポイント {bi+1}", "body": b}
                    for bi, b in enumerate(bullets[:3])
                ]
            elif idx == 0:
                scene_obj["kind"] = "hero"
                bullets = md_info.get("bullets") or nar_lines[1:4]
                scene_obj["bullets"] = bullets[:4]
            elif "シート" in title or "成果物" in title:
                scene_obj["kind"] = "worksheet"
                scene_obj["worksheetItems"] = md_info.get("numbered") or nar_lines[:6]
                scene_obj["checklist"] = md_info.get("bullets") or nar_lines[-3:]
            else:
                scene_obj["kind"] = "cards"
                items = md_info.get("bullets") or md_info.get("numbered") or nar_lines[1:5]
                scene_obj["cards"] = [
                    {"tag": f"POINT {bi+1}", "title": b[:22], "body": b}
                    for bi, b in enumerate(items[:4])
                ]

            scenes.append(scene_obj)

        jobs_out[job_id] = {
            "videoType": vjob.get("video_type") or job_entry.get("video_type", "ダイジェスト"),
            "lessonTitle": vjob.get("lesson_title") or lesson_title,
            "scenes": scenes,
        }

    compiled = {"jobs": jobs_out}
    auto_out = package_dir / "scenes_spec.auto.json"
    auto_out.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    return compiled


def resolve_scenes_spec(package_dir: Path, scenes_json_arg: str, lesson_id: str, batch_job_ids: list[str]) -> dict:
    """
    3-Stage Deterministic Resolution:
    1. Explicit `--scenes-json` path if provided
    2. Pre-curated golden spec in `<skill_root>/examples/<lesson_id>_scenes_spec.json`
    3. Zero-LLM deterministic compiler from `video-job.json` + `video-script.md`
    """
    if scenes_json_arg:
        p = Path(scenes_json_arg).resolve()
        if p.exists():
            print(f"[Spec] Using explicit scenes spec: {p}")
            return json.loads(p.read_text(encoding="utf-8"))

    golden_path = SKILL_ROOT / "examples" / f"{lesson_id}_scenes_spec.json"
    if golden_path.exists():
        spec = json.loads(golden_path.read_text(encoding="utf-8"))
        jobs_map = spec.get("jobs", spec)
        if all(jid in jobs_map for jid in batch_job_ids):
            print(f"[Spec] Using pre-validated golden spec: {golden_path}")
            return spec

    print(f"[Spec] Auto-compiling scenes spec deterministically from {package_dir}...")
    return auto_compile_package_to_scenes(package_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-Command Deterministic Course Video Package Renderer")
    parser.add_argument("--package-dir", required=True, help="Path to lesson package (contains batch.json)")
    parser.add_argument("--scenes-json", default="", help="Optional path to scenes_spec.json (auto-resolved if omitted)")
    parser.add_argument("--downloads-dir", default="/Users/jungosakamoto/Downloads", help="Optional Downloads copy dir")
    parser.add_argument("--zip-name", default="", help="Optional zip filename in Downloads dir")
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help="Fish Audio reference_id")
    parser.add_argument("--tts-workers", type=int, default=4, help="Parallel Fish Audio TTS workers")
    parser.add_argument("--output-suffix", default="", help="Optional suffix for output filenames (e.g. '_下位モデル')")
    args = parser.parse_args()

    package_dir = Path(args.package_dir).resolve()
    batch_file = package_dir / "batch.json"
    if not batch_file.exists():
        raise FileNotFoundError(f"batch.json not found in {package_dir}")

    batch_data = json.loads(batch_file.read_text(encoding="utf-8"))
    course_id = batch_data.get("courseId") or batch_data.get("course_id", "ai-user-a01")
    lesson_id = batch_data.get("lessonId") or batch_data.get("lesson_id", package_dir.name)
    jobs = batch_data.get("jobs", [])
    batch_job_ids = [j.get("jobId") or j.get("id") for j in jobs]

    scenes_spec = resolve_scenes_spec(package_dir, args.scenes_json, lesson_id, batch_job_ids)
    jobs_map = scenes_spec.get("jobs", scenes_spec)

    for jid in batch_job_ids:
        if jid not in jobs_map:
            raise ValueError(f"Job '{jid}' from batch.json is missing in resolved scenes spec")

    print(f"[1/4] Syncing images for {lesson_id} with chmod 644 & xattr -cr...")
    sync_package_images(package_dir, lesson_id)

    api_key = get_fish_api_key()
    work_dir = REMOTION_ROOT / lesson_id / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    SCENES_OUT_DIR.mkdir(parents=True, exist_ok=True)

    rendered_mp4s: list[Path] = []

    for job in jobs:
        job_id = job.get("jobId") or job.get("id")
        rel_output = job.get("output") or f"{job.get('folder', job_id)}/{job_id}.mp4"
        job_spec = jobs_map[job_id]
        scenes = job_spec["scenes"]
        video_type = job_spec.get("videoType") or job.get("video_type") or job.get("type", "full")
        lesson_title = (
            job_spec.get("lessonTitle")
            or batch_data.get("lessonTitle")
            or batch_data.get("lesson_title", "")
        )

        print(
            f"\n[2/4] Synthesizing Fish Audio {DEFAULT_MODEL} (voice={args.voice_id[:8]}..., workers={args.tts_workers}) for {job_id} ({len(scenes)} scenes)..."
        )
        job_audio_dir = work_dir / job_id
        job_audio_dir.mkdir(parents=True, exist_ok=True)

        # Parallel TTS synthesis for 3-4x speedup
        def _synth_one(item: tuple[int, dict]) -> tuple[int, Path, float]:
            idx, sc = item
            sc_id = sc["id"]
            mp3_path = job_audio_dir / f"{idx:02d}_{sc_id}.mp3"
            dur = synthesize_tts(sc["narration"], mp3_path, api_key, voice_id=args.voice_id)
            return idx, mp3_path, dur

        with ThreadPoolExecutor(max_workers=max(1, args.tts_workers)) as pool:
            synth_results = list(pool.map(_synth_one, list(enumerate(scenes))))

        synth_results.sort(key=lambda x: x[0])

        mp3_list: list[Path] = []
        cursor_frame = 0
        built_scenes = []

        for idx, mp3_path, dur in synth_results:
            sc = scenes[idx]
            sc_id = sc["id"]
            frames = max(90, int(math.ceil(dur * FPS)))
            sc_copy = dict(sc)
            for img_key in ("image", "secondImage"):
                if sc_copy.get(img_key):
                    clean_img = sc_copy[img_key].replace("../", "").lstrip("./")
                    if not clean_img.startswith(f"{lesson_id}/"):
                        sc_copy[img_key] = f"{lesson_id}/{clean_img}"
            sc_copy["frames"] = frames
            sc_copy["startFrame"] = cursor_frame
            built_scenes.append(sc_copy)
            cursor_frame += frames
            mp3_list.append(mp3_path)
            print(f"  - [{idx+1:02d}/{len(scenes):02d}] {sc_id}: {dur:.2f}s ({frames}f)")

        combined_mp3 = PUBLIC_DIR / lesson_id / f"{job_id}.mp3"
        combined_mp3.parent.mkdir(parents=True, exist_ok=True)
        concat_mp3_files(mp3_list, combined_mp3)

        build_payload = {
            "id": job_id,
            "courseId": course_id,
            "lessonId": lesson_id,
            "videoType": video_type,
            "lessonTitle": lesson_title,
            "fps": FPS,
            "width": 1920,
            "height": 1080,
            "totalFrames": cursor_frame,
            "scenes": built_scenes,
        }

        build_json_path = SCENES_OUT_DIR / f"{job_id}.build.json"
        build_json_path.write_text(
            json.dumps(build_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        props_json_path = work_dir / f"{job_id}.props.json"
        props_json_path.write_text(
            json.dumps({"id": job_id, "build": build_payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        silent_mp4 = work_dir / f"{job_id}.silent.mp4"
        final_pkg_mp4 = package_dir / rel_output
        final_pkg_mp4.parent.mkdir(parents=True, exist_ok=True)

        remotion_cli = REMOTION_ROOT / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        print(f"[3/4] Rendering Remotion CourseVideo for {job_id} ({cursor_frame} frames)...")
        subprocess.run(
            [
                "node",
                str(remotion_cli),
                "render",
                "src/index.ts",
                "CourseVideo",
                str(silent_mp4),
                f"--props={props_json_path}",
                "--concurrency=6",
            ],
            cwd=str(REMOTION_ROOT),
            check=True,
        )

        print(f"[4/4] Muxing video + s2-pro audio (-map 0:v:0 -map 1:a:0) -> {final_pkg_mp4}...")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_mp4),
                "-i",
                str(combined_mp3),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(final_pkg_mp4),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        verify_mp4(final_pkg_mp4)
        rendered_mp4s.append(final_pkg_mp4)

        if args.downloads_dir:
            dl_dir = Path(args.downloads_dir)
            out_stem = f"{job_id}{args.output_suffix}"
            dl_mp4 = dl_dir / f"{out_stem}.mp4"
            shutil.copy2(final_pkg_mp4, dl_mp4)
            # If suffix provided, also copy to a dedicated suffixed folder
            if args.output_suffix:
                suffixed_dir = dl_dir / f"{package_dir.name.replace(' ', '_')}_videos{args.output_suffix}"
                suffixed_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(final_pkg_mp4, suffixed_dir / f"{out_stem}.mp4")
            # Also sync standard unzipped output directories in Downloads
            for sub_dir_name in (
                f"{lesson_id}_videos",
                f"{lesson_id}_2_videos",
                f"{lesson_id}_videos 2",
                f"{package_dir.name.replace(' ', '_')}_videos",
            ):
                candidate_dir = dl_dir / sub_dir_name
                if candidate_dir.exists() and candidate_dir.is_dir():
                    shutil.copy2(final_pkg_mp4, candidate_dir / f"{job_id}.mp4")
            print(f"  ✓ Verified & synced to {dl_mp4}")

    zip_name = args.zip_name or f"{package_dir.name.replace(' ', '_')}_videos{args.output_suffix}.zip"
    if args.downloads_dir:
        zip_path = Path(args.downloads_dir) / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for mp4 in rendered_mp4s:
                entry_name = f"{mp4.stem}{args.output_suffix}{mp4.suffix}"
                zf.write(mp4, arcname=entry_name)
            notes = package_dir / "confirmation-notes.md"
            if notes.exists():
                zf.write(notes, arcname="confirmation-notes.md")
        print(f"\n✓ Created ZIP archive: {zip_path}")


if __name__ == "__main__":
    main()
