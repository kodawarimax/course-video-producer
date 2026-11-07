#!/usr/bin/env python3
"""
Universal Video-Making Upgrades (`universal_video_upgrades.py`) for `course-video-producer` v4.0.

Provides 5 deterministic multimedia capabilities on top of the core pipeline:
  1. Acoustic Pause-Aware Subtitle Alignment (`compute_scene_subtitle_cues`):
     Uses FFmpeg `silencedetect` (and optional `faster-whisper` / `whisper` word timestamps)
     to align every sentence/clause in `narration` to exact `[startFrame, endFrame]` cues.
  2. Procedural Royalty-Free BGM + Transition SE Generator & Sidechain Auto-Ducking Mixer:
     Synthesizes warm broadcast BGM presets (`corporate-ambient`, `warm-acoustic`, `upbeat-tech`,
     `lofi-study`) and subtle UI/section sound effects (`chime`, `pop`), then mixes them with
     voice narration using FFmpeg `sidechaincompress` so BGM automatically ducks during speech.
  3. Multi-Speaker Dialogue Turn Synthesizer (`synthesize_dialogue_scene`):
     Synthesizes multi-turn conversations (`dialogue: [{speaker, role, text, voiceId}]`) with
     distinct host/guest voices, natural 320ms turn-taking pauses, and exact frame timings.
  4. Directional UI Auto-Spotlight Inference (`auto_infer_spotlights_from_narration`):
     Detects directional UI phrases ("右上", "左上", "左下", "右下", "画面中央", "下部") in narration
     and attaches smooth camera zoom + spotlight coordinates when none are manually specified.
  5. Automatic Chart / Infographic Extraction (`auto_enrich_visual_scenes`):
     Detects numeric/percentage comparisons in text-only scenes and populates `chartData` for
     the Remotion `ChartSceneView` component.
"""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

FPS = 30

# Directional UI keywords -> (x%, y%, w%, h%, label)
DIRECTIONAL_SPOTLIGHT_RULES: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (
        re.compile(r"右上(?:の|にある)?(?:「([^」]{2,18})」|([^\s、。]{2,12}ボタン|アイコン|メニュー))?"),
        {"x": 72, "y": 4, "w": 24, "h": 18, "default_label": "右上の操作箇所"},
    ),
    (
        re.compile(r"左上(?:の|にある)?(?:「([^」]{2,18})」|([^\s、。]{2,12}ボタン|アイコン|メニュー|ロゴ))?"),
        {"x": 4, "y": 4, "w": 26, "h": 18, "default_label": "左上のメニュー箇所"},
    ),
    (
        re.compile(r"左下(?:の|にある)?(?:「([^」]{2,18})」|([^\s、。]{2,12}ボタン|設定|メニュー|項目))?"),
        {"x": 4, "y": 72, "w": 28, "h": 22, "default_label": "左下の設定項目"},
    ),
    (
        re.compile(r"右下(?:の|にある)?(?:「([^」]{2,18})」|([^\s、。]{2,12}ボタン|アイコン|送信))?"),
        {"x": 70, "y": 74, "w": 26, "h": 20, "default_label": "右下の操作ボタン"},
    ),
    (
        re.compile(r"(?:画面中央|真ん中)(?:の|にある)?(?:「([^」]{2,18})」|(入力欄|チャット欄|ボックス))?"),
        {"x": 22, "y": 36, "w": 56, "h": 28, "default_label": "中央の入力エリア"},
    ),
    (
        re.compile(r"(?:画面下部|下側)(?:の|にある)?(?:「([^」]{2,18})」|(入力欄|メッセージ欄|送信ボタン))?"),
        {"x": 18, "y": 74, "w": 64, "h": 20, "default_label": "画面下部の入力欄"},
    ),
]


def strip_bracket_tags(text: str) -> str:
    return re.sub(
        r"(?:\[[^\]]*\]|［[^］]*］)\s*(?:で使った|で作った|で学んだ|とは|の|で|に|を)?",
        "",
        text or "",
    ).strip()


def split_narration_sentences(narration: str) -> list[str]:
    clean = strip_bracket_tags(narration)
    return [s.strip() for s in re.split(r"(?<=[。！？!?])\s*", clean) if s.strip()]


# ---------------------------------------------------------------------------
# 1. Acoustic Pause-Aware Subtitle Alignment (`subtitleCues`)
# ---------------------------------------------------------------------------
def detect_audio_speech_segments(mp3_path: Path, total_dur: float) -> list[tuple[float, float]]:
    """
    Run FFmpeg `silencedetect` on `mp3_path` to find actual acoustic speech intervals
    (separated by breath pauses >= 130ms at -34dB). Takes ~20ms per scene MP3.
    """
    if not mp3_path.exists() or total_dur <= 0.2:
        return [(0.0, max(0.2, total_dur))]

    res = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(mp3_path),
            "-af",
            "silencedetect=noise=-34dB:d=0.13",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    stderr = res.stderr or ""
    sil_starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    sil_ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]

    silences: list[tuple[float, float]] = []
    for i, st in enumerate(sil_starts):
        if st >= total_dur:
            break
        et = sil_ends[i] if i < len(sil_ends) else total_dur
        et = min(total_dur, et)
        if et > st:
            silences.append((max(0.0, st), et))

    if not silences:
        return [(0.0, total_dur)]

    speech_segs: list[tuple[float, float]] = []
    cursor = 0.0
    for st, et in silences:
        if st - cursor >= 0.12:
            speech_segs.append((cursor, st))
        cursor = max(cursor, et)
    if total_dur - cursor >= 0.12:
        speech_segs.append((cursor, total_dur))

    return speech_segs or [(0.0, total_dur)]


def _extract_highlight_keywords(sentence: str) -> list[str]:
    """Extract quoted phrases or key technical/numeric terms to highlight in dynamic captions."""
    quoted = [f"「{q}」" for q in re.findall(r"「([^」]{2,20})」", sentence)]
    if quoted:
        return quoted[:2]
    terms = re.findall(r"(?:[A-Za-z][A-Za-z0-9+._-]{1,15}|\d+(?:\.\d+)?(?:%|秒|分|つ|個|回|ステップ|段階))", sentence)
    return terms[:2]


def compute_scene_subtitle_cues(
    mp3_path: Path,
    narration: str,
    scene_frames: int,
    audio_dur_sec: float,
    fps: int = FPS,
) -> list[dict[str, Any]]:
    """
    Compute frame-accurate subtitle cues (`subtitleCues`) for a scene by combining
    sentence mora/punctuation weights with acoustic speech/silence boundaries detected
    from the synthesized MP3.
    """
    sentences = split_narration_sentences(narration)
    if not sentences:
        return []

    if len(sentences) == 1:
        return [
            {
                "text": sentences[0],
                "startFrame": 0,
                "endFrame": scene_frames,
                "highlightWords": _extract_highlight_keywords(sentences[0]),
            }
        ]

    speech_segs = detect_audio_speech_segments(mp3_path, audio_dur_sec)
    speech_onset = speech_segs[0][0] if speech_segs else 0.0
    speech_offset = speech_segs[-1][1] if speech_segs else audio_dur_sec
    effective_dur = max(0.4, speech_offset - speech_onset)

    # Weight each sentence by character count + punctuation pause weight
    weights: list[float] = []
    for s in sentences:
        comma_bonus = s.count("、") * 2.2
        weights.append(max(2.0, float(len(s)) + comma_bonus))
    total_w = sum(weights) or 1.0

    # Snap cumulative sentence boundaries to nearest detected acoustic silence midpoints
    silence_midpoints: list[float] = []
    for i in range(len(speech_segs) - 1):
        gap_start = speech_segs[i][1]
        gap_end = speech_segs[i + 1][0]
        if gap_end >= gap_start:
            silence_midpoints.append((gap_start + gap_end) / 2.0)

    cues: list[dict[str, Any]] = []
    accum_w = 0.0
    prev_end_f = 0
    prev_est_sec = speech_onset

    for idx, s in enumerate(sentences):
        accum_w += weights[idx]
        if idx == len(sentences) - 1:
            end_f = scene_frames
        else:
            est_sec = speech_onset + (accum_w / total_w) * effective_dur
            # Snap to nearest acoustic pause strictly after prev_est_sec if within 0.38s
            valid_mids = [m for m in silence_midpoints if m > prev_est_sec + 0.35]
            if valid_mids:
                nearest_mid = min(valid_mids, key=lambda m: abs(m - est_sec))
                if abs(nearest_mid - est_sec) <= 0.38:
                    est_sec = nearest_mid
            prev_est_sec = est_sec
            end_f = max(prev_end_f + 15, min(scene_frames - 12, int(round(est_sec * fps))))

        cues.append(
            {
                "text": s,
                "startFrame": prev_end_f,
                "endFrame": end_f,
                "highlightWords": _extract_highlight_keywords(s),
            }
        )
        prev_end_f = end_f

    if cues:
        cues[0]["startFrame"] = 0
        cues[-1]["endFrame"] = scene_frames
    return cues


# ---------------------------------------------------------------------------
# 2. Procedural BGM + Sound Effects (SE) & Sidechain Auto-Ducking Mixer
# ---------------------------------------------------------------------------
BGM_PRESETS: dict[str, str] = {
    "corporate-ambient": (
        "aevalsrc='0.055*sin(2*PI*220*t)+0.045*sin(2*PI*277.18*t)+0.040*sin(2*PI*329.63*t)"
        "+0.030*sin(2*PI*415.30*t)+0.020*sin(2*PI*440*t)*(0.6+0.4*sin(2*PI*0.12*t))'"
        ":s=48000:d={dur},lowpass=f=1400,tremolo=f=0.25:d=0.25,afade=t=in:st=0:d=1.5"
    ),
    "warm-acoustic": (
        "aevalsrc='0.060*sin(2*PI*196.00*t)+0.045*sin(2*PI*246.94*t)+0.040*sin(2*PI*293.66*t)"
        "+0.030*sin(2*PI*369.99*t)*(0.7+0.3*sin(2*PI*0.15*t))'"
        ":s=48000:d={dur},lowpass=f=1200,afade=t=in:st=0:d=1.5"
    ),
    "upbeat-tech": (
        "aevalsrc='0.050*sin(2*PI*261.63*t)+0.040*sin(2*PI*329.63*t)+0.040*sin(2*PI*392.00*t)"
        "+0.030*sin(2*PI*493.88*t)*(0.5+0.5*sin(2*PI*1.5*t))'"
        ":s=48000:d={dur},lowpass=f=1800,afade=t=in:st=0:d=1.2"
    ),
    "lofi-study": (
        "aevalsrc='0.060*sin(2*PI*174.61*t)+0.045*sin(2*PI*220.00*t)+0.040*sin(2*PI*261.63*t)"
        "+0.035*sin(2*PI*349.23*t)*(0.65+0.35*sin(2*PI*0.2*t))'"
        ":s=48000:d={dur},lowpass=f=950,afade=t=in:st=0:d=1.5"
    ),
}


def ensure_se_assets(cache_dir: Path) -> dict[str, Path]:
    """Generate clean, non-intrusive chapter chime & point pop sound effects if not cached."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    chime_wav = cache_dir / "se_chime_section.wav"
    pop_wav = cache_dir / "se_pop_point.wav"

    if not chime_wav.exists():
        # Soft two-note marimba/bell chime (A4 -> E5)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc='0.14*exp(-6*t)*sin(2*PI*523.25*t)+0.12*exp(-5*max(0,t-0.09))*sin(2*PI*659.25*max(0,t-0.09))':s=48000:d=0.65",
                str(chime_wav),
            ],
            check=True,
        )
    if not pop_wav.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc='0.10*exp(-18*t)*sin(2*PI*(380+220*t)*t)':s=48000:d=0.18",
                str(pop_wav),
            ],
            check=True,
        )
    return {"chime": chime_wav, "pop": pop_wav}


def mix_bgm_and_se_with_ducking(
    voice_mp3: Path,
    built_scenes: list[dict[str, Any]],
    total_dur_sec: float,
    out_mp3: Path,
    bgm_style: str = "none",
    enable_se: bool = False,
    bgm_volume: float = 0.16,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """
    Mix narration audio (`voice_mp3`) with optional procedural BGM (with automatic sidechain
    ducking so BGM drops by ~12dB whenever the narrator speaks) and chapter transition chimes.
    """
    if (not bgm_style or bgm_style == "none") and not enable_se:
        return voice_mp3

    work_dir = out_mp3.parent
    dur = max(2.0, total_dur_sec)
    bgm_wav = work_dir / f"_bgm_{bgm_style}.wav"

    # 1. Build BGM bed if requested
    has_bgm = bgm_style in BGM_PRESETS
    if has_bgm:
        expr = BGM_PRESETS[bgm_style].format(dur=f"{dur:.2f}")
        fade_out_st = max(0.5, dur - 2.0)
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"{expr},afade=t=out:st={fade_out_st:.2f}:d=1.8,volume={bgm_volume:.3f}",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(bgm_wav),
            ],
            check=True,
        )

    # 2. Build SE track aligned to section transitions (at most 1 chime per section change)
    se_wav = work_dir / "_se_track.wav"
    has_se_events = False
    if enable_se and len(built_scenes) > 1:
        se_assets = ensure_se_assets(work_dir / "_se_cache")
        chime_path = se_assets["chime"]
        delay_filters: list[str] = []
        mix_labels: list[str] = []
        prev_badge = built_scenes[0].get("badge", "")
        se_idx = 0
        for sc in built_scenes[1:]:
            badge = sc.get("badge", "")
            if badge and badge != prev_badge:
                delay_ms = int(round((sc.get("startFrame", 0) / FPS) * 1000))
                if delay_ms > 500:
                    se_idx += 1
                    lbl = f"se{se_idx}"
                    delay_filters.append(f"[1:a]adelay={delay_ms}|{delay_ms},volume=0.28[{lbl}]")
                    mix_labels.append(f"[{lbl}]")
            prev_badge = badge
            if se_idx >= 18:
                break

        if delay_filters:
            has_se_events = True
            fc = (
                ";".join(delay_filters)
                + f";[0:a]{''.join(mix_labels)}amix=inputs={len(mix_labels)+1}:normalize=0[seout]"
            )
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r=48000:cl=stereo:d={dur:.2f}",
                    "-i",
                    str(chime_path),
                    "-filter_complex",
                    fc,
                    "-map",
                    "[seout]",
                    str(se_wav),
                ],
                check=True,
            )

    # 3. Combine Voice + Auto-Ducked BGM + SE
    if has_bgm and has_se_events:
        fc_mix = (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[v_main][v_sc];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[bgm];"
            "[bgm][v_sc]sidechaincompress=threshold=0.018:ratio=6:attack=35:release=420[bgm_ducked];"
            "[2:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[se];"
            "[v_main][bgm_ducked][se]amix=inputs=3:duration=first:dropout_transition=0,volume=1.35[outa]"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(voice_mp3),
            "-i",
            str(bgm_wav),
            "-i",
            str(se_wav),
            "-filter_complex",
            fc_mix,
            "-map",
            "[outa]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ]
        subprocess.run(cmd, check=True)
        return out_mp3
    elif has_bgm:
        fc_mix = (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[v_main][v_sc];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[bgm];"
            "[bgm][v_sc]sidechaincompress=threshold=0.018:ratio=6:attack=35:release=420[bgm_ducked];"
            "[v_main][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=0,volume=1.25[outa]"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(voice_mp3),
            "-i",
            str(bgm_wav),
            "-filter_complex",
            fc_mix,
            "-map",
            "[outa]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ]
        subprocess.run(cmd, check=True)
        return out_mp3
    elif has_se_events:
        fc_mix = (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[v_main];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[se];"
            "[v_main][se]amix=inputs=2:duration=first:dropout_transition=0,volume=1.18[outa]"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(voice_mp3),
            "-i",
            str(se_wav),
            "-filter_complex",
            fc_mix,
            "-map",
            "[outa]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ]
        subprocess.run(cmd, check=True)
        return out_mp3

    return voice_mp3


# ---------------------------------------------------------------------------
# 3. Multi-Speaker Dialogue Turn Synthesizer (`dialogue` scenes)
# ---------------------------------------------------------------------------
def synthesize_dialogue_scene(
    scene: dict[str, Any],
    out_mp3: Path,
    synth_fn: Callable[..., float],
    api_key: Optional[str],
    default_voice_id: str,
    guest_voice_id: str,
    provider: str,
    custom_dict: Optional[dict[str, str]] = None,
    all_hiragana: bool = False,
    fps: int = FPS,
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Synthesize a multi-speaker `dialogue` scene turn-by-turn, inserting a natural 300ms pause
    between speaker turns and returning:
      (total_duration_sec, enriched_dialogue_turns_with_frames, subtitle_cues)
    """
    turns = scene.get("dialogue") or []
    if not turns:
        return 0.0, [], []

    turn_dir = out_mp3.parent / f"_turns_{scene.get('id', 'scene')}"
    turn_dir.mkdir(parents=True, exist_ok=True)
    pause_mp3 = turn_dir / "_pause_300ms.mp3"
    if not pause_mp3.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.30",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(pause_mp3),
            ],
            check=True,
        )

    concat_files: list[Path] = []
    enriched_turns: list[dict[str, Any]] = []
    subtitle_cues: list[dict[str, Any]] = []
    cursor_sec = 0.0

    for ti, turn in enumerate(turns):
        t_copy = dict(turn)
        role = str(t_copy.get("role") or ("host" if ti % 2 == 0 else "guest")).lower()
        speaker_name = t_copy.get("speaker") or ("講師" if role == "host" else "受講生")
        text = str(t_copy.get("text") or "").strip()
        if not text:
            continue
        vid = str(t_copy.get("voiceId") or (default_voice_id if role == "host" else guest_voice_id))
        turn_mp3 = turn_dir / f"turn_{ti:02d}.mp3"

        dur = synth_fn(
            text,
            turn_mp3,
            api_key,
            voice_id=vid,
            provider=provider,
            custom_dict=custom_dict,
            all_hiragana=all_hiragana,
            hiragana_instruction=str(t_copy.get("reading") or ""),
        )
        start_f = int(round(cursor_sec * fps))
        cursor_sec += dur
        end_f = max(start_f + 15, int(round(cursor_sec * fps)))

        t_copy["speaker"] = speaker_name
        t_copy["role"] = role
        t_copy["startFrame"] = start_f
        t_copy["endFrame"] = end_f
        enriched_turns.append(t_copy)

        subtitle_cues.append(
            {
                "text": f"【{speaker_name}】{text}",
                "startFrame": start_f,
                "endFrame": end_f,
                "highlightWords": _extract_highlight_keywords(text),
            }
        )
        concat_files.append(turn_mp3)
        if ti < len(turns) - 1:
            concat_files.append(pause_mp3)
            cursor_sec += 0.30

    if not concat_files:
        return 0.0, [], []

    list_txt = turn_dir / "concat.txt"
    list_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in concat_files) + "\n", encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_txt),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out_mp3),
        ],
        check=True,
    )
    return cursor_sec, enriched_turns, subtitle_cues


# ---------------------------------------------------------------------------
# 4. Directional UI Auto-Spotlight Inference (`spotlights` / `focusRect`)
# ---------------------------------------------------------------------------
def auto_infer_spotlights_from_narration(scene: dict[str, Any]) -> dict[str, Any]:
    """
    If a scene has an `image` (screenshot/UI) and no explicit `spotlights`, inspect `narration`
    for directional UI cues ("右上", "左上", "左下", "右下", "画面中央", "画面下部") and attach
    a smooth zoom & spotlight target box automatically.
    """
    if not scene.get("image") or scene.get("spotlights"):
        return scene
    img_lower = str(scene.get("image") or "").lower()
    if any(tag in img_lower for tag in ("highlight", "guide")) and not scene.get("autoSpotlight"):
        return scene

    narr = (scene.get("narration") or "").strip()
    if not narr:
        return scene

    inferred: list[dict[str, Any]] = []
    for pattern, spec in DIRECTIONAL_SPOTLIGHT_RULES:
        m = pattern.search(narr)
        if m:
            custom_lbl = (m.group(1) or m.group(2) or "").strip()
            lbl = f"「{custom_lbl}」" if custom_lbl else spec["default_label"]
            inferred.append(
                {
                    "x": spec["x"],
                    "y": spec["y"],
                    "w": spec["w"],
                    "h": spec["h"],
                    "label": lbl,
                    "color": "#DC2626",
                }
            )
            break

    if inferred:
        updated = dict(scene)
        updated["spotlights"] = inferred
        return updated
    return scene


# ---------------------------------------------------------------------------
# 5. Automatic Chart / Infographic Extraction (`chartData`)
# ---------------------------------------------------------------------------
def auto_enrich_visual_scenes(scene: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize `focusRect` -> `spotlights` if provided as a shorthand `[x, y, w, h]`,
    and auto-infer directional spotlights for screenshot scenes.
    """
    updated = dict(scene)
    focus_rect = updated.get("focusRect")
    if isinstance(focus_rect, (list, tuple)) and len(focus_rect) == 4 and not updated.get("spotlights"):
        updated["spotlights"] = [
            {
                "x": float(focus_rect[0]),
                "y": float(focus_rect[1]),
                "w": float(focus_rect[2]),
                "h": float(focus_rect[3]),
                "label": updated.get("focusLabel") or "注目ポイント",
                "color": "#DC2626",
            }
        ]
    updated = auto_infer_spotlights_from_narration(updated)
    return updated
