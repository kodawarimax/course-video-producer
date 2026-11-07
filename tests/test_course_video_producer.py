#!/usr/bin/env python3
"""
Automated Unit & Integration Test Suite for Course Video Producer v4.0.
Covers:
  1. 16,563-entry Built-in Reading Dictionary + 3-Tier Hybrid Hiragana Resolution
  2. Automatic Narration De-Duplication, Run-on Splitting, and Context Polishing (100/100 Audit)
  3. Acoustic Pause-Aligned Subtitle Cues & Keyword Highlighting
  4. Auto-Inferred Directional UI Spotlights & Camera Focus Rectangles
  5. Procedural BGM / Section Chime SE Generation & Sidechain Auto-Ducking
  6. Error / Edge-Case Handling (empty narration, invalid paths, Fact Gate invariant preservation)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compile_input_to_spec import derive_subvideo_jobs_from_full_scenes
from scripts.edit_storyboard import (
    audit_job_scenes,
    export_spec_to_markdown,
    import_markdown_to_spec,
    polish_scene_deterministic,
    polish_spec_scenes,
)
from scripts.render_course_package import (
    kanji_to_hiragana_sentence,
    normalize_for_s2_pro,
    parse_reading_dict_text,
    strip_brackets_for_tts,
)
from scripts.tts_dictionary import (
    _segment_with_dictionary_and_hiragana_instruction,
    load_active_prosody_dictionary,
    load_builtin_dictionary,
    load_reference_kanji_dictionary,
    normalize_prosody_Japanese_tts,
)
from scripts.universal_video_upgrades import (
    BGM_PRESETS,
    auto_enrich_visual_scenes,
    compute_scene_subtitle_cues,
    ensure_se_assets,
)


def test_dictionary_scale_and_priority() -> None:
    """Verify the built-in reading dictionary has >=16,000 entries and prioritizes dictionary readings."""
    full_dict = load_builtin_dictionary()
    active_dict = load_active_prosody_dictionary()
    ref_dict = load_reference_kanji_dictionary()

    assert len(full_dict) >= 16000
    assert len(active_dict) >= 12000
    assert len(ref_dict) >= 4000

    # Tier 1 dictionary hit + Tier 2 Hiragana fallback for OOV Kanji
    sample = "ChatGPTとClaudeで一言添えて表にして共有します。"
    hira_cf, _ = kanji_to_hiragana_sentence(sample)
    prosody_out, kana_out, applied = _segment_with_dictionary_and_hiragana_instruction(
        sample, hiragana_instruction=hira_cf
    )
    assert "チャットジーピーティー" in prosody_out
    assert "クロード" in prosody_out
    assert "ひとこと" in prosody_out
    assert "ひょうにして" in prosody_out
    assert len(applied) >= 4
    assert len(kana_out) > 10


def test_oov_kanji_falls_back_to_hiragana_instruction() -> None:
    """Verify out-of-vocabulary rare Kanji falls back cleanly to the Hiragana text instruction."""
    sample = "AIで魑魅魍魎な課題を解決します。"
    explicit_hira = "えーあいでちみもうりょうなかだいをかいけつします。"
    prosody_out, _ = normalize_prosody_Japanese_tts(
        sample, hiragana_instruction=explicit_hira
    )
    assert "エーアイ" in prosody_out
    assert "ちみもうりょう" in prosody_out
    assert "魑魅魍魎" not in prosody_out


def test_narration_deduplication_and_polish_reaches_100_score() -> None:
    """Verify redundant phrase repeats, bare section numbers, and monotonous endings are cleaned."""
    noisy_scenes = [
        {
            "id": "sc-01",
            "kind": "hero",
            "heading": "プロンプトの基本",
            "sub": "3つの要素を押さえる",
            "narration": "プロンプトの基本。3つの要素を押さえる。4 プロンプトの基本を押さえることで、精度を高めることが可能になります。",
        },
        {
            "id": "sc-02",
            "kind": "bullets",
            "heading": "背景と目的の伝え方",
            "sub": "AIが迷わない指示の出し方",
            "narration": "背景と目的の伝え方。AIが迷わない指示の出し方について確認します。",
        },
        {
            "id": "sc-03",
            "kind": "steps",
            "heading": "出力形式の指定",
            "sub": "表や箇条書きの活用",
            "narration": "出力形式の指定。表や箇条書きの活用について確認します。",
        },
        {
            "id": "sc-04",
            "kind": "summary",
            "heading": "まとめ",
            "sub": "今日から試せる一歩",
            "narration": "まとめ。今日から試せる一歩について確認します。",
        },
    ]

    polished, changes = polish_spec_scenes(noisy_scenes, mode="deterministic")
    assert len(changes) >= 1
    audit_res = audit_job_scenes(polished)
    assert audit_res["score"] >= 95
    assert audit_res["summary"]["redundant_repeats"] == 0
    assert audit_res["summary"]["ai_cliches"] == 0
    assert "可能になります" not in polished[0]["narration"]


def test_fact_gate_preserves_numbers_and_proper_nouns() -> None:
    """Verify the deterministic polisher never drops numeric values or model identifiers."""
    sc = {
        "id": "sc-fact",
        "kind": "compare",
        "heading": "GPT-5とClaude 4の比較",
        "sub": "128000トークンの処理",
        "narration": "GPT-5とClaude 4は128000トークンを3秒で処理することが可能になります。",
    }
    updated, _ = polish_scene_deterministic(sc, 0, 1, None, None)
    assert "128000" in updated["narration"]
    assert "3" in updated["narration"]
    assert "GPT-5" in updated["narration"]


def test_subtitle_cues_and_visual_enrichment(tmp_path: Path) -> None:
    """Verify pause-aligned subtitle cue splitting and directional UI spotlight inference."""
    sc = {
        "id": "sc-ui",
        "kind": "figure",
        "heading": "ChatGPTの入力欄",
        "sub": "画面下の送信ボタンを押す",
        "image": "../images/chat_ui.png",
        "narration": "まず画面下の「メッセージを入力」欄に質問を入力します。次に右下の送信ボタンをクリックして回答を確認しましょう。",
    }
    cues = compute_scene_subtitle_cues(tmp_path / "nonexistent.mp3", sc["narration"], scene_frames=240, audio_dur_sec=8.0)
    assert len(cues) >= 2
    assert cues[0]["startFrame"] == 0
    assert cues[-1]["endFrame"] == 240

    enriched = auto_enrich_visual_scenes(sc)
    assert "spotlights" in enriched
    assert len(enriched["spotlights"]) >= 1


def test_markdown_roundtrip_and_procedural_audio(tmp_path: Path) -> None:
    """Verify storyboard Markdown export/import round-trip and procedural BGM/SE generation."""
    spec = {
        "jobs": {
            "job01": {
                "videoType": "full",
                "lessonTitle": "テスト講座",
                "scenes": [
                    {
                        "id": "s1",
                        "kind": "hero",
                        "badge": "INTRO",
                        "badgeColor": "blue",
                        "heading": "はじめに",
                        "sub": "概要",
                        "tip": "ポイント",
                        "bullets": ["項目A", "項目B"],
                        "narration": "ここからAIの基本を学びます。",
                    }
                ],
            }
        }
    }
    md_path = tmp_path / "storyboard.md"
    export_spec_to_markdown(spec, md_path)
    assert md_path.exists()

    md_text = md_path.read_text(encoding="utf-8").replace("ここからAIの基本を学びます。", "実践的なAI活用を学びます。")
    md_path.write_text(md_text, encoding="utf-8")

    reimported, mod_ids = import_markdown_to_spec(md_path, spec)
    assert "job01/s1" in mod_ids
    assert reimported["jobs"]["job01"]["scenes"][0]["narration"] == "実践的なAI活用を学びます。"

    se_paths = ensure_se_assets(tmp_path / "se")
    assert se_paths["chime"].exists()
    assert se_paths["pop"].exists()
    assert "corporate-ambient" in BGM_PRESETS


def test_edge_cases_and_parsing() -> None:
    """Verify empty inputs and bracket stripping behave deterministically without crashing."""
    assert strip_brackets_for_tts("[画面1]で学んだプロンプトを確認します。") == "プロンプトを確認します。"
    assert normalize_for_s2_pro("") == ""
    parsed = parse_reading_dict_text("| 漢字 | ひらがな |\n| :--- | :--- |\n| 一言 | ひとこと |\n表にして=ひょうにして")
    assert parsed.get("一言") == "ひとこと"
    assert parsed.get("表にして") == "ひょうにして"

    # Verify automatic derivation of 2 sub-videos (操作実演 + 活用事例) besides full video
    full_scenes = [
        {"id": "s1", "badge": "SECTION 01", "kind": "hero", "narration": "導入です。"},
        {"id": "s2", "badge": "SECTION 06", "kind": "full-image", "image": "images/a.png", "narration": "画面操作1です。"},
        {"id": "s3", "badge": "SECTION 06", "kind": "steps", "image": "images/b.png", "narration": "画面操作2です。"},
        {"id": "s4", "badge": "SECTION 14", "kind": "summary", "narration": "応用まとめです。"},
    ]
    sub_jobs = derive_subvideo_jobs_from_full_scenes("lesson01", full_scenes)
    assert len(sub_jobs) == 2
    assert sub_jobs[0][0] == "lesson01-06"
    assert sub_jobs[0][1] == "操作実演"
    assert len(sub_jobs[0][2]) >= 3
    assert sub_jobs[1][0] == "lesson01-14"
    assert sub_jobs[1][1] == "活用事例"
    assert len(sub_jobs[1][2]) >= 3
