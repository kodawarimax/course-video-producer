#!/usr/bin/env python3
"""
Post-Generation Manual & AI Storyboard / Japanese Context Editor (`edit_storyboard.py`)
for `course-video-producer` v3.1.

Provides 6 workflows after initial package compilation or video generation:
  1. `audit`     : Diagnose Japanese naturalness & cross-scene context flow (100-pt scorecard)
  2. `polish`    : Holistic AI / deterministic Japanese & context transition rewriter
                   with an Invariant Fact Gate (preserves numbers, proper nouns, and assets)
  3. `export-md` : Export `scenes_spec.json` -> human/AI-editable `storyboard.md`
  4. `import-md` : Import edited `storyboard.md` -> `scenes_spec.json` with diff report
  5. `set-scene` : Surgical CLI edit for a single scene (narration, heading, sub, tip, kind, bullets)
  6. `serve`     : Launch local browser GUI (`http://127.0.0.1:8765`) for interactive manual + AI editing,
                   single-scene TTS audio preview, and 4-second single-scene Remotion video preview.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("course_video_producer")

# ---------------------------------------------------------------------------
# 1. Broadcast Japanese De-Slop & Context Transition Rules (Deterministic)
# ---------------------------------------------------------------------------
AI_SLOP_REWRITES: list[tuple[str, str, str]] = [
    (r"することが可能になります", "できるようになります", "冗長表現（〜することが可能になります）"),
    (r"ことが可能になります", "ことができます", "冗長表現（〜ことが可能になります）"),
    (r"することが可能です", "できます", "冗長表現（〜することが可能です）"),
    (r"ことが可能です", "ことができます", "冗長表現（〜ことが可能です）"),
    (r"することが可能となります", "できるようになります", "冗長表現（〜することが可能となります）"),
    (r"ことが可能となります", "ことができます", "冗長表現（〜ことが可能となります）"),
    (r"を行うことができます", "を行えます", "冗長表現（〜を行うことができます）"),
    (r"することができます", "できます", "冗長表現（〜することができます）"),
    (r"非常に重要な役割を果たします(?:と言えるでしょう|と言えます)?", "重要な役割を果たしています", "AI誇張表現（非常に重要な役割を果たします）"),
    (r"非常に重要なポイントとなります", "重要なポイントです", "AI誇張表現（非常に重要なポイントとなります）"),
    (r"非常に重要です", "重要です", "AI誇張表現（非常に重要です）"),
    (r"極めて重要です", "非常に大切です", "AI誇張表現（極めて重要です）"),
    (r"と言えるでしょう", "と言えます", "AI常套句（〜と言えるでしょう）"),
    (r"といえるでしょう", "といえます", "AI常套句（〜といえるでしょう）"),
    (r"ではないでしょうか", "です", "AI常套句（〜ではないでしょうか）"),
    (r"という観点から", "という点から", "翻訳調（〜という観点から）"),
    (r"という観点において", "という点で", "翻訳調（〜という観点において）"),
    (r"において重要な", "で重要な", "硬い書き言葉（〜において重要な）"),
    (r"を実現することができます", "を実現できます", "冗長表現（〜を実現することができます）"),
    (r"というメリットがあります", "という強みがあります", "定型表現（〜というメリットがあります）"),
    (r"ということが挙げられます", "が挙げられます", "冗長表現（〜ということが挙げられます）"),
    (r"について解説してまいります", "を解説します", "過剰敬語（解説してまいります）"),
    (r"について見ていきましょう", "を見ていきましょう", "冗長助詞（について見ていきましょう）"),
    (r"まずはじめに、", "まず、", "重複表現（まずはじめに）"),
    (r"まず最初に、", "まず、", "重複表現（まず最初に）"),
    (r"それぞれの特徴について", "それぞれの特徴を", "冗長助詞（〜について）"),
]

CONTEXT_BRIDGES_BY_KIND: dict[str, list[str]] = {
    "comparison": [
        "続いて、具体的な違いを比較して見ていきましょう。",
        "ここで、それぞれの違いを並べて確認してみます。",
    ],
    "table": [
        "ここで、全体像を表で整理しておきましょう。",
        "一覧表でポイントを比較してみます。",
    ],
    "steps": [
        "ここからは、実際の進め方を順番に確認していきましょう。",
        "具体的なステップを順を追って見ていきます。",
    ],
    "grid": [
        "主なポイントを一覧で見ていきましょう。",
        "押さえておきたい要素を整理します。",
    ],
    "callout": [
        "ここで、特に意識しておきたい重要ポイントです。",
        "実務でつまずきやすい注意点を確認しておきましょう。",
    ],
    "kpi": [
        "具体的な数値と目安を確認しておきましょう。",
    ],
    "video-clip": [
        "実際の画面操作の動きを見ていきましょう。",
    ],
}

OPENING_BOILERPLATE_RE = re.compile(
    r"^(?:このセクションでは、?|このパートでは、?|このスライドでは、?|ここでは、?|次に、?|続いて、?)"
)


def _extract_invariants(text: str) -> set[str]:
    """Extract numbers (normalized without leading zeros), percentages, and ASCII technical tokens that must not be lost."""
    raw_nums = re.findall(r"\d+(?:\.\d+)?%?", text)
    nums: set[str] = set()
    for n in raw_nums:
        if re.fullmatch(r"0+\d+", n):
            nums.add(str(int(n)))
        else:
            nums.add(n)
    ascii_tokens = {
        t
        for t in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{1,}", text)
        if t.lower() not in {"ai", "ok", "ng", "vs", "pc", "id", "ui", "ux", "it", "web"}
    }
    return nums | ascii_tokens


def verify_invariants(original_text: str, rewritten_text: str) -> tuple[bool, list[str]]:
    """Ensure all numbers and key English technical terms in original_text remain in rewritten_text."""
    orig_inv = _extract_invariants(original_text)
    new_inv = _extract_invariants(rewritten_text)
    missing = sorted(orig_inv - new_inv)
    return (len(missing) == 0), missing


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？])", text.strip())
    return [p.strip() for p in parts if p.strip()]


RUN_ON_PERIOD_RE = re.compile(
    r"(できる|わかる|られる|一つ|ひとつ)(?=(今日は|今回は|教材の|まずは|ここからは|たとえば|具体的には))"
)
BARE_SECTION_PAIR_RE = re.compile(r"(?<!セクション)\b0?([1-9]|1\d)\s*(?:または|か)\s*0?([1-9]|1\d)で")
BARE_SECTION_SINGLE_RE = re.compile(r"(?<!セクション)\b0?([1-9]|1\d)で(使った|試した|選んだ|作成した|入力した)")


def _opening_signature(narration: str) -> str:
    sents = _split_sentences(narration)
    if not sents:
        return ""
    first = sents[0]
    m = OPENING_BOILERPLATE_RE.match(first)
    if m:
        return m.group(0).rstrip("、")
    return first[:10]


def audit_job_scenes(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Perform a holistic Japanese & narrative context audit across all scenes of a job.
    Returns a structured report with a 100-point score and per-scene issues.
    """
    scene_reports: list[dict[str, Any]] = []
    total_issues = 0
    cliche_hits_total = 0
    repetitive_opening_count = 0
    monotonous_ending_count = 0
    long_sentence_count = 0
    slide_overlap_count = 0
    redundant_repeat_count = 0

    prev_open_sig = ""
    prev_last_sent = ""
    prev_sents_set: set[str] = set()
    open_sig_counts: dict[str, int] = {}

    for idx, sc in enumerate(scenes):
        sc_id = sc.get("id", f"scene-{idx+1:02d}")
        narr = (sc.get("narration") or "").strip()
        heading = (sc.get("heading") or "").strip()
        sub = (sc.get("sub") or "").strip()
        bullets = sc.get("bullets") or []
        issues: list[dict[str, str]] = []

        # 1. AI cliché / slop expressions
        for pattern, replacement, label in AI_SLOP_REWRITES:
            if re.search(pattern, narr):
                issues.append(
                    {
                        "type": "ai_cliche",
                        "label": label,
                        "suggestion": f"「{pattern}」→「{replacement}」へ簡潔化",
                    }
                )
                cliche_hits_total += 1

        # 1b. Run-on missing period (bullet-to-paragraph concatenation glitch)
        if RUN_ON_PERIOD_RE.search(narr):
            issues.append(
                {
                    "type": "run_on_sentence",
                    "label": "文の区切り（。）の欠落による文連結",
                    "suggestion": "箇条書きと本文の境界に句点（。）を挿入して自然な文区切りに修正",
                }
            )
            redundant_repeat_count += 1

        # 1c. Bare section number ("07で使った", "07または08で")
        if BARE_SECTION_PAIR_RE.search(narr) or BARE_SECTION_SINGLE_RE.search(narr):
            issues.append(
                {
                    "type": "bare_section_number",
                    "label": "裸のセクション番号表記（「07で」等）",
                    "suggestion": "耳で聞いてわかりやすい「セクション7で」「先ほど試した」へ自然化",
                }
            )
            cliche_hits_total += 1

        # 2. Repetitive opening or verbatim heading repeat at start of narration
        open_sig = _opening_signature(narr)
        if open_sig:
            open_sig_counts[open_sig] = open_sig_counts.get(open_sig, 0) + 1
        if idx > 0 and open_sig and (open_sig == prev_open_sig or open_sig_counts.get(open_sig, 0) >= 3):
            issues.append(
                {
                    "type": "repetitive_opening",
                    "label": f"冒頭表現の重複（「{open_sig}…」）",
                    "suggestion": "前シーンからの文脈接続詞（「続いて」「一方で」「具体的には」等）へ変更推奨",
                }
            )
            repetitive_opening_count += 1
        elif heading and len(heading) >= 5 and narr.startswith(heading):
            issues.append(
                {
                    "type": "heading_repeat",
                    "label": "見出し文字列の冒頭丸読み",
                    "suggestion": "スライド見出しをそのまま読まず、導入の問いかけや文脈接続から開始",
                }
            )
            repetitive_opening_count += 1
        prev_open_sig = open_sig

        # 3. Monotonous sentence endings (3+ consecutive です。 or ます。 OR consecutive scenes ending identically)
        sents = _split_sentences(narr)
        desu_streak = 0
        masu_streak = 0
        for s in sents:
            if s.endswith("です。"):
                desu_streak += 1
                masu_streak = 0
            elif s.endswith("ます。"):
                masu_streak += 1
                desu_streak = 0
            else:
                desu_streak = 0
                masu_streak = 0
            if desu_streak >= 3 or masu_streak >= 3:
                ending_lbl = "〜です。" if desu_streak >= 3 else "〜ます。"
                issues.append(
                    {
                        "type": "monotonous_ending",
                        "label": f"文末の単調連続（{ending_lbl}が3文以上連続）",
                        "suggestion": "「〜です」「〜ます」「〜になります」「〜でしょう」を織り交ぜてリズムを改善",
                    }
                )
                monotonous_ending_count += 1
                break

        last_sent = sents[-1] if sents else ""
        if idx > 0 and last_sent and prev_last_sent:
            for suffix in ("を確認しましょう。", "を使い分けましょう。", "を見ていきましょう。"):
                if last_sent.endswith(suffix) and prev_last_sent.endswith(suffix):
                    issues.append(
                        {
                            "type": "monotonous_ending",
                            "label": f"連続シーンでの同一文末（「〜{suffix}」の連続）",
                            "suggestion": "前後のシーンで「〜を見てみましょう」「〜を確かめてみます」等に変化をつける",
                        }
                    )
                    monotonous_ending_count += 1
                    break
        prev_last_sent = last_sent

        # 3b. Intra-scene & cross-scene redundant repetition check
        seen_in_scene: set[str] = set()
        quotes_in_scene = [q for q in re.findall(r"「([^」]{8,})」", narr)]
        has_dup_quote = len(quotes_in_scene) != len(set(quotes_in_scene))
        if has_dup_quote or narr.count("大丈夫です") >= 3:
            issues.append(
                {
                    "type": "intra_scene_repeat",
                    "label": "同一シーン内のフレーズ・例文の重複リピート",
                    "suggestion": "同じ例文や同一フレーズ（「大丈夫です」等）の重複を整理し1回に集約",
                }
            )
            redundant_repeat_count += 1
        for s in sents:
            norm_s = re.sub(r"[\s、。]", "", s)
            if len(norm_s) >= 10 and norm_s in seen_in_scene:
                issues.append(
                    {
                        "type": "intra_scene_repeat",
                        "label": f"同一シーン内の重複文（「{s[:24]}…」）",
                        "suggestion": "重複している文を削除して簡潔化",
                    }
                )
                redundant_repeat_count += 1
                break
            seen_in_scene.add(norm_s)
            if idx > 0 and len(norm_s) >= 14 and norm_s in prev_sents_set:
                issues.append(
                    {
                        "type": "cross_scene_repeat",
                        "label": f"前シーンとの同一文リピート（「{s[:24]}…」）",
                        "suggestion": "直前シーンと重複する説明文を省略または言い換え",
                    }
                )
                redundant_repeat_count += 1
                break
        prev_sents_set = {re.sub(r"[\s、。]", "", s) for s in sents if len(s) >= 14}

        # 4. Breath / sentence length (>95 chars without pause or >130 chars total)
        for s in sents:
            if len(s) > 125 or (len(s) > 85 and "、" not in s):
                issues.append(
                    {
                        "type": "long_sentence",
                        "label": f"一文が長すぎ・息継ぎ不足（{len(s)}文字）",
                        "suggestion": "読点（、）の追加または2文への分割でTTSの息継ぎを自然化",
                    }
                )
                long_sentence_count += 1
                break

        # 5. Slide-reading overlap check
        slide_concat = "".join([heading, sub] + [str(b) for b in bullets])
        slide_clean = re.sub(r"[\s、。・！？()（）「」]", "", slide_concat)
        narr_clean = re.sub(r"[\s、。・！？()（）「」]", "", narr)
        if slide_clean and narr_clean and len(narr_clean) > 15:
            ratio = difflib.SequenceMatcher(None, slide_clean, narr_clean).ratio()
            if ratio >= 0.78:
                issues.append(
                    {
                        "type": "slide_reading",
                        "label": f"スライド文字の丸読み（一致率 {int(ratio*100)}%）",
                        "suggestion": "箇条書きは要点に絞り、ナレーションでは背景・具体例・補足を語る構成へ分離",
                    }
                )
                slide_overlap_count += 1

        total_issues += len(issues)
        scene_reports.append(
            {
                "index": idx + 1,
                "id": sc_id,
                "kind": sc.get("kind", "hero"),
                "heading": heading,
                "narration_length": len(narr),
                "sentence_count": len(sents),
                "issues": issues,
            }
        )

    n_scenes = max(1, len(scenes))
    penalty = min(
        60,
        cliche_hits_total * 3
        + repetitive_opening_count * 4
        + monotonous_ending_count * 3
        + long_sentence_count * 3
        + slide_overlap_count * 4
        + redundant_repeat_count * 4,
    )
    score = max(40, 100 - int(round(penalty * (20 / max(10, n_scenes)))))

    return {
        "score": score,
        "scene_count": len(scenes),
        "total_issues": total_issues,
        "summary": {
            "ai_cliches": cliche_hits_total,
            "repetitive_openings": repetitive_opening_count,
            "monotonous_endings": monotonous_ending_count,
            "long_sentences": long_sentence_count,
            "slide_reading_overlap": slide_overlap_count,
            "redundant_repeats": redundant_repeat_count,
        },
        "scenes": scene_reports,
    }


# ---------------------------------------------------------------------------
# 2. Deterministic & LLM Holistic Context / Japanese Polisher
# ---------------------------------------------------------------------------
def _polish_sentence_rhythm(narration: str) -> str:
    """Fix monotonous sentence endings and insert breath commas in overly long clauses."""
    sents = _split_sentences(narration)
    if not sents:
        return narration

    # Vary 3+ consecutive 〜です。 or 〜ます。
    out_sents: list[str] = []
    desu_run = 0
    masu_run = 0
    for idx, s in enumerate(sents):
        if s.endswith("です。"):
            desu_run += 1
            masu_run = 0
            if desu_run >= 3:
                s = re.sub(r"重要です。$", "重要になります。", s)
                s = re.sub(r"有効です。$", "効果を発揮します。", s)
                s = re.sub(r"特徴です。$", "特徴があります。", s)
                s = re.sub(r"ポイントです。$", "ポイントになります。", s)
                s = re.sub(r"おすすめです。$", "おすすめします。", s)
                desu_run = 0
        elif s.endswith("ます。"):
            masu_run += 1
            desu_run = 0
            if masu_run >= 3:
                s = re.sub(r"なっています。$", "いるのが特徴です。", s)
                s = re.sub(r"できます。$", "可能です。", s)
                s = re.sub(r"ようになります。$", "ようになるのも強みです。", s)
                s = re.sub(r"を果たしています。$", "を果たすのが特徴です。", s)
                masu_run = 0
        else:
            desu_run = 0
            masu_run = 0

        # Insert breath pause in long comma-less stretches (>75 chars)
        if len(s) > 75 and s.count("、") == 0:
            s = re.sub(r"(ため|ので|から|ですが|ものの|によって)(?=[^\s、])", r"\1、", s, count=1)

        out_sents.append(s)

    return "".join(out_sents)


def _dedup_and_clean_narration(
    narr: str,
    idx: int,
    prev_sc: Optional[dict[str, Any]] = None,
) -> tuple[str, list[str]]:
    """
    Deterministically eliminate redundant repeats, run-on missing periods, bare section numbers,
    duplicate quoted examples, and cross-scene identical sentences/endings.
    """
    changes: list[str] = []

    # 1. Insert missing periods at bullet-to-paragraph concatenation boundaries
    fixed_runon = RUN_ON_PERIOD_RE.sub(r"\1。", narr)
    if fixed_runon != narr:
        changes.append("文連結箇所に句点（。）を自動挿入")
        narr = fixed_runon

    # 2. Normalize bare section numbers ("07で使った" -> "セクション7で使った", "07または08で" -> "セクション7や8で")
    fixed_sec = BARE_SECTION_PAIR_RE.sub(r"セクション\1や\2で", narr)
    fixed_sec = BARE_SECTION_SINGLE_RE.sub(r"セクション\1で\2", fixed_sec)
    if fixed_sec != narr:
        changes.append("裸のセクション番号（「07で」等）を自然な話し言葉（「セクション7で」）へ変換")
        narr = fixed_sec

    # 3. Back-to-back repeated quoted subject ("「X」をオフにします。「X」をオフにすることと" -> "「X」をオフにします。ただし、これをオフにすることと")
    fixed_subj = re.sub(
        r"「([^」]{4,})」をオフにします。「\1」をオフにすることと",
        r"「\1」をオフにします。ただし、これをオフにすることと",
        narr,
    )
    fixed_subj = re.sub(
        r"「([^」]{4,})」(を[^。]{2,14}ます)。「\1」を",
        r"「\1」\2。これを",
        fixed_subj,
    )
    if fixed_subj != narr:
        changes.append("連続する同一主語の反復を指示語（「これを」）へ自然化")
        narr = fixed_subj

    # 4. Vary 2+ occurrences of "大丈夫です" within the same scene
    if narr.count("大丈夫です") >= 2:
        parts = narr.split("大丈夫です")
        rebuilt = parts[0]
        repl_choices = ["大丈夫です", "問題ありません", "十分です", "構いません"]
        for pi, tail in enumerate(parts[1:]):
            rebuilt += repl_choices[min(pi, len(repl_choices) - 1)] + tail
        if rebuilt != narr:
            changes.append("同一シーン内の「大丈夫です」の反復を「問題ありません」「十分です」へ多様化")
            narr = rebuilt

    # 5. Intra-scene sentence deduplication & duplicate quoted-example cleanup
    sents = _split_sentences(narr)
    if len(sents) >= 2:
        # Count quoted examples (>= 8 chars) across sentences; if an earlier sentence is a raw step-dump
        # that repeats the exact same quote explained in a later sentence, drop the redundant earlier dump.
        quote_to_sent_indices: dict[str, list[int]] = {}
        for si, s in enumerate(sents):
            for q in re.findall(r"「([^」]{8,})」", s):
                quote_to_sent_indices.setdefault(q, []).append(si)
        drop_indices: set[int] = set()
        for q, s_idxs in quote_to_sent_indices.items():
            if len(s_idxs) >= 2:
                # Keep the later fuller explanatory sentence, drop the earlier bullet-concatenation sentence
                # if dropping it preserves all invariants in the remaining sentences
                cand_idx = s_idxs[0]
                remaining = "".join(s for i, s in enumerate(sents) if i != cand_idx)
                ok_inv, _ = verify_invariants(narr, remaining)
                if ok_inv:
                    drop_indices.add(cand_idx)

        seen_norm: set[str] = set()
        dedup_sents: list[str] = []
        for si, s in enumerate(sents):
            if si in drop_indices:
                changes.append("同一シーン内で重複していた例文説明を1回に集約")
                continue
            norm = re.sub(r"[\s、。]", "", s)
            if len(norm) >= 10 and norm in seen_norm:
                changes.append(f"同一シーン内の重複文を削除（「{s[:20]}…」）")
                continue
            seen_norm.add(norm)
            dedup_sents.append(s)
        if dedup_sents:
            sents = dedup_sents

    # 6. Cross-scene duplicate sentence removal (against prev_sc)
    if prev_sc and len(sents) >= 2:
        prev_sents = _split_sentences((prev_sc.get("narration") or "").strip())
        prev_norms = {re.sub(r"[\s、。]", "", ps) for ps in prev_sents if len(ps) >= 14}
        filtered_cross: list[str] = []
        for s in sents:
            norm = re.sub(r"[\s、。]", "", s)
            if len(norm) >= 14 and norm in prev_norms and (len(filtered_cross) > 0 or len(sents) > 1):
                changes.append(f"前シーンと重複していた文を整理（「{s[:22]}…」）")
                continue
            filtered_cross.append(s)
        if filtered_cross:
            sents = filtered_cross

    # 7. Cross-scene consecutive ending diversification
    if prev_sc and sents:
        prev_sents = _split_sentences((prev_sc.get("narration") or "").strip())
        prev_last = prev_sents[-1] if prev_sents else ""
        cur_last = sents[-1]
        if prev_last.endswith("を確認しましょう。") and cur_last.endswith("を確認しましょう。"):
            alt_endings = ["を見てみましょう。", "を確かめてみます。", "に注目してみましょう。", "を押さえておきましょう。"]
            alt = alt_endings[idx % len(alt_endings)]
            sents[-1] = re.sub(r"を確認しましょう。$", alt, cur_last)
            changes.append(f"連続シーンの同一文末「〜を確認しましょう。」→「〜{alt}」へ多様化")
        elif prev_last.endswith("を使い分けましょう。") and cur_last.endswith("を使い分けましょう。"):
            sents[-1] = re.sub(r"を使い分けましょう。$", "を選び分けましょう。", cur_last)
            changes.append("連続シーンの同一文末「〜を使い分けましょう。」→「〜を選び分けましょう。」へ多様化")

    return "".join(sents), changes


def polish_scene_deterministic(
    sc: dict[str, Any],
    idx: int,
    total_scenes: int,
    prev_sc: Optional[dict[str, Any]] = None,
    used_openings: Optional[dict[str, int]] = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Deterministically polish a single scene's Japanese narration and slide copy
    considering its position and surrounding scenes.
    Returns (updated_scene, list_of_applied_changes).
    """
    updated = copy.deepcopy(sc)
    changes: list[str] = []
    narr = (updated.get("narration") or "").strip()
    if not narr:
        return updated, changes

    orig_narr = narr

    # Step 0: Run-on period fix, bare section number normalization, intra/cross-scene deduplication
    dedup_narr, dedup_changes = _dedup_and_clean_narration(narr, idx, prev_sc=prev_sc)
    if dedup_narr != narr:
        narr = dedup_narr
        changes.extend(dedup_changes)

    # Step 1: De-slop AI clichés
    for pattern, replacement, label in AI_SLOP_REWRITES:
        new_narr = re.sub(pattern, replacement, narr)
        if new_narr != narr:
            changes.append(f"{label}: 「{pattern}」→「{replacement}」")
            narr = new_narr

    # Step 2: Context-aware opening diversification
    heading = (updated.get("heading") or "").strip()
    kind = updated.get("kind", "hero")
    open_sig = _opening_signature(narr)
    if used_openings is not None and open_sig:
        used_openings[open_sig] = used_openings.get(open_sig, 0) + 1

    # If scene starts with verbatim heading followed by period, turn it into a natural bridge
    if heading and len(heading) >= 4 and narr.startswith(heading + "。"):
        rest = narr[len(heading) + 1 :].lstrip()
        clean_h = re.sub(
            r"^(?:SECTION\s*\d+[:：]?\s*|第\d+[章節][:：]?\s*|\d+[.．:：]\s*)",
            "",
            heading,
            flags=re.I,
        ).strip() or heading
        if rest:
            if idx == 0:
                bridge = f"まずは「{clean_h}」から見ていきましょう。"
            elif idx == total_scenes - 1:
                bridge = f"最後に「{clean_h}」を整理します。"
            elif kind in CONTEXT_BRIDGES_BY_KIND:
                opts = CONTEXT_BRIDGES_BY_KIND[kind]
                bridge = opts[idx % len(opts)]
            else:
                bridge = f"続いて、「{clean_h}」のポイントを見ていきましょう。"
            narr = f"{bridge}{rest}"
            changes.append("見出し丸読みの冒頭を文脈導入ブリッジへ変換")
    elif (
        idx > 0
        and open_sig in ("ここでは", "このセクションでは", "このスライドでは", "次に")
        and used_openings is not None
        and used_openings.get(open_sig, 0) >= 2
    ):
        bridges = CONTEXT_BRIDGES_BY_KIND.get(
            kind,
            ["続いて、", "さらに、", "もう一つ押さえておきたいのが、", "実務で意識したい点として、"],
        )
        rep = bridges[idx % len(bridges)]
        if rep.endswith("。"):
            # Replace "ここでは、" with a full bridge clause if appropriate, or adverbial connector
            connectors = ["続いて、", "さらに、", "あわせて、", "もう一点、"]
            rep_conn = connectors[idx % len(connectors)]
            narr = OPENING_BOILERPLATE_RE.sub(rep_conn, narr, count=1)
            changes.append(f"重複した冒頭「{open_sig}」→「{rep_conn.rstrip('、')}」へ多様化")
        else:
            narr = OPENING_BOILERPLATE_RE.sub(rep, narr, count=1)
            changes.append(f"重複した冒頭「{open_sig}」→「{rep.rstrip('、')}」へ多様化")

    # Step 3: Sentence ending rhythm & breath pause optimization
    rhythm_narr = _polish_sentence_rhythm(narr)
    if rhythm_narr != narr:
        changes.append("文末リズム（です/ます連続）と息継ぎ読点の最適化")
        narr = rhythm_narr

    # Step 4: Invariant Fact Gate check (account for prev_sc when cross-scene duplicate sentences were removed)
    prev_context = (prev_sc.get("narration") or "") if prev_sc else ""
    ok, missing = verify_invariants(orig_narr, f"{narr} {prev_context}")
    if not ok:
        # Never lose numbers or key identifiers
        narr = orig_narr
        changes = [f"[Fact Gate 保護] 数値・固有名詞保護のため変更スキップ ({missing})"]

    updated["narration"] = narr

    # Step 5: Sync narration_prosody, narration_tts, narration_kana with 16,563-entry dictionary + Hiragana fallback
    if narr != orig_narr or not updated.get("narration_prosody") or not updated.get("narration_kana"):
        try:
            try:
                from .render_course_package import kanji_to_hiragana_sentence
                from .tts_dictionary import (
                    _segment_with_dictionary_and_hiragana_instruction,
                    normalize_prosody_Japanese_tts,
                )
            except ImportError:
                from render_course_package import kanji_to_hiragana_sentence
                from tts_dictionary import (
                    _segment_with_dictionary_and_hiragana_instruction,
                    normalize_prosody_Japanese_tts,
                )

            hira_cf, _ = kanji_to_hiragana_sentence(narr)
            hira_inst = hira_cf if narr != orig_narr else (updated.get("narration_tts") or updated.get("narration_kana") or hira_cf)
            prosody_text, applied_repls = normalize_prosody_Japanese_tts(narr, hiragana_instruction=hira_inst)
            _, dict_first_kana, _ = _segment_with_dictionary_and_hiragana_instruction(narr, hiragana_instruction=hira_inst)
            updated["narration_prosody"] = prosody_text
            updated["applied_replacements"] = [[k, v] for k, v in applied_repls]
            updated["narration_kana"] = dict_first_kana or hira_inst
            updated["narration_tts"] = dict_first_kana or hira_inst
        except Exception as exc:
            logger.debug("Failed to sync prosody/kana in polish_scene_deterministic: %s", exc)

    # Also clean AI clichés in sub / tip if present
    for field in ("sub", "tip"):
        val = (updated.get(field) or "").strip()
        if val:
            new_val = val
            for pattern, replacement, _ in AI_SLOP_REWRITES:
                new_val = re.sub(pattern, replacement, new_val)
            if new_val != val:
                updated[field] = new_val
                changes.append(f"スライド {field} の冗長表現を簡潔化")

    return updated, changes


def _try_llm_context_polish(
    scenes: list[dict[str, Any]],
    instruction: str = "",
    target_scene_filter: Optional[str] = None,
) -> Optional[list[dict[str, Any]]]:
    """
    Optional holistic LLM context polisher via `gemini` CLI or OpenAI API if available.
    Uses a strict JSON contract and runs `verify_invariants` on every scene afterward.
    Returns None if no LLM CLI/key is available so caller falls back to deterministic polish.
    """
    gemini_bin = shutil.which("gemini")
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not gemini_bin and not openai_key:
        return None

    digest = [
        {
            "id": sc["id"],
            "kind": sc.get("kind", "hero"),
            "heading": sc.get("heading", ""),
            "sub": sc.get("sub", ""),
            "bullets": sc.get("bullets", []),
            "tip": sc.get("tip", ""),
            "narration": sc.get("narration", ""),
        }
        for sc in scenes
        if (not target_scene_filter or sc["id"] == target_scene_filter)
    ]

    extra_rule = f"\n追加編集指示: {instruction}\n" if instruction else ""
    prompt = (
        "あなたはプロの放送作家・日本語ナレーション校閲者です。\n"
        "以下の動画ストーリーボード配列（JSON）について、動画全体の文脈の繋がり（前後シーンの接続）と"
        "耳で聞いて自然で明快な日本語ナレーションになるように推敲してください。\n"
        "【絶対遵守ルール】\n"
        "1. 各要素の `id` は1文字も変更しないこと。\n"
        "2. 原文に含まれる数値・パーセンテージ・英字の製品名やモデル名は絶対に削除・改変しないこと。\n"
        "3. 「〜と言えるでしょう」「〜することが可能になります」「非常に重要」などのAI常套句・翻訳調を排除すること。\n"
        "4. 前後のシーンで同じ冒頭表現（「ここでは」「このセクションでは」等）が続かないよう自然な接続詞で繋ぐこと。\n"
        f"{extra_rule}"
        "出力は推敲後の JSON 配列（`[{\"id\": ..., \"heading\": ..., \"sub\": ..., \"tip\": ..., \"narration\": ...}, ...]`）のみを返してください。\n\n"
        + json.dumps(digest, ensure_ascii=False, indent=2)
    )

    raw_response = ""
    try:
        if openai_key:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": "gpt-4o-mini",
                        "temperature": 0.2,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                ).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_response = data["choices"][0]["message"]["content"]
        elif gemini_bin:
            proc = subprocess.run(
                [gemini_bin, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if proc.returncode == 0:
                raw_response = proc.stdout
    except Exception:
        return None

    m = re.search(r"\[\s*\{[\s\S]*\}\s*\]", raw_response)
    if not m:
        return None
    try:
        rewritten_list = json.loads(m.group(0))
        by_id = {item["id"]: item for item in rewritten_list if isinstance(item, dict) and "id" in item}
    except Exception:
        return None

    merged: list[dict[str, Any]] = []
    for sc in scenes:
        cand = by_id.get(sc["id"])
        if not cand:
            merged.append(sc)
            continue
        new_sc = copy.deepcopy(sc)
        new_narr = (cand.get("narration") or "").strip()
        if new_narr:
            ok, _ = verify_invariants(sc.get("narration", ""), new_narr)
            if ok:
                new_sc["narration"] = new_narr
        for fld in ("heading", "sub", "tip"):
            if cand.get(fld) and isinstance(cand[fld], str):
                ok_f, _ = verify_invariants(sc.get(fld, ""), cand[fld])
                if ok_f:
                    new_sc[fld] = cand[fld].strip()
        merged.append(new_sc)
    return merged


def polish_spec_scenes(
    scenes: list[dict[str, Any]],
    mode: str = "deterministic",
    instruction: str = "",
    target_scene: Optional[str] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run holistic Japanese & context polishing across `scenes`.
    Returns (polished_scenes, change_log).
    """
    working_scenes = copy.deepcopy(scenes)
    change_log: list[dict[str, Any]] = []

    if mode == "llm":
        llm_res = _try_llm_context_polish(working_scenes, instruction=instruction, target_scene_filter=target_scene)
        if llm_res is not None:
            working_scenes = llm_res

    used_openings: dict[str, int] = {}
    final_scenes: list[dict[str, Any]] = []
    for idx, sc in enumerate(working_scenes):
        sc_id = sc.get("id", f"scene-{idx+1:02d}")
        if target_scene and sc_id != target_scene and str(idx + 1) != str(target_scene):
            final_scenes.append(sc)
            continue
        prev_sc = final_scenes[-1] if final_scenes else None
        polished_sc, changes = polish_scene_deterministic(
            sc, idx, len(working_scenes), prev_sc=prev_sc, used_openings=used_openings
        )
        orig_narr = scenes[idx].get("narration", "")
        new_narr = polished_sc.get("narration", "")
        if orig_narr != new_narr or changes:
            change_log.append(
                {
                    "index": idx + 1,
                    "id": sc_id,
                    "changes": changes or ["LLM文脈リライト適用"],
                    "before_narration": orig_narr,
                    "after_narration": new_narr,
                }
            )
        final_scenes.append(polished_sc)

    return final_scenes, change_log


# ---------------------------------------------------------------------------
# 3. Bidirectional Storyboard Markdown (`export-md` ⇄ `import-md`)
# ---------------------------------------------------------------------------
def export_spec_to_markdown(spec: dict[str, Any], out_md: Path, custom_dict: Optional[dict[str, str]] = None) -> None:
    """Export `scenes_spec.json` into a clean, human & AI-editable `storyboard.md`."""
    try:
        from .render_course_package import kanji_to_hiragana_sentence
    except ImportError:
        from render_course_package import kanji_to_hiragana_sentence

    jobs = spec.get("jobs", spec)
    lines: list[str] = [
        "# 🎬 Course Video Storyboard (双方向マニュアル・AI編集シート)",
        "",
        "> この Markdown ファイルを直接編集（見出し・サブ見出し・箇条書き・ポイント・ナレーション・ひらがな読みの書き換え、",
        "> または `## Scene` ブロックの並び替え）した後、以下のコマンドで `scenes_spec.json` に安全に反映できます：",
        "> `python3 edit_storyboard.py import-md --package-dir <パッケージパス>`",
        "",
    ]

    for job_id, job_data in jobs.items():
        lesson_title = job_data.get("lessonTitle", "")
        vtype = job_data.get("videoType", "full")
        lines.append(f"# JOB: `{job_id}` — {lesson_title} (`{vtype}`)")
        lines.append("")
        for idx, sc in enumerate(job_data.get("scenes", [])):
            sc_id = sc.get("id", f"scene-{idx+1:02d}")
            kind = sc.get("kind", "hero")
            badge = sc.get("badge", f"SECTION {idx+1:02d}")
            bcolor = sc.get("badgeColor", "blue")
            heading = sc.get("heading", "")
            sub = sc.get("sub", "")
            tip = sc.get("tip", "")
            img = sc.get("image", "")
            vid = sc.get("video", "")
            bullets = sc.get("bullets") or []
            narr = sc.get("narration", "")
            narr_kana = sc.get("narration_kana") or sc.get("narration_tts") or sc.get("reading") or ""
            if not narr_kana and narr:
                narr_kana, _ = kanji_to_hiragana_sentence(narr, custom_dict=custom_dict)

            lines.append(f"## Scene {idx+1:02d}: `{sc_id}` [{kind}]")
            lines.append(f"- **badge**: {badge} ({bcolor})")
            lines.append(f"- **heading**: {heading}")
            lines.append(f"- **sub**: {sub}")
            lines.append(f"- **tip**: {tip}")
            if img:
                lines.append(f"- **image**: `{img}`")
            if vid:
                lines.append(f"- **video**: `{vid}`")
            lines.append("")
            lines.append("### Bullets")
            if bullets:
                for b in bullets:
                    lines.append(f"- {b}")
            else:
                lines.append("<!-- 箇条書きなし -->")
            lines.append("")
            lines.append("### Narration")
            lines.append(narr)
            lines.append("")
            lines.append("### Reading (ひらがな読みベース)")
            lines.append(narr_kana)
            lines.append("")
            lines.append("---")
            lines.append("")

    out_md.write_text("\n".join(lines), encoding="utf-8")


def import_markdown_to_spec(md_path: Path, orig_spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Parse an edited `storyboard.md` and merge changes into `orig_spec` without losing
    complex fields (`table`, `cards`, `columns`, `steps`, `stats`, etc.).
    """
    new_spec = copy.deepcopy(orig_spec)
    jobs = new_spec.get("jobs", new_spec)
    md_text = md_path.read_text(encoding="utf-8")
    modified_ids: list[str] = []

    # Index all existing scenes by (job_id, scene_id) and by scene_id globally
    scene_lookup: dict[str, dict[str, Any]] = {}
    for jid, jdata in jobs.items():
        for sc in jdata.get("scenes", []):
            scene_lookup[sc["id"]] = sc

    job_blocks = re.split(r"(?m)^#\s+JOB:\s+`([^`]+)`.*$", md_text)
    if len(job_blocks) < 3:
        raise ValueError("storyboard.md に `# JOB: `<job_id>`` ヘッダが見つかりません。")

    for j_idx in range(1, len(job_blocks) - 1, 2):
        job_id = job_blocks[j_idx].strip()
        job_body = job_blocks[j_idx + 1]
        if job_id not in jobs:
            continue

        scene_chunks = re.split(r"(?m)^##\s+Scene\s+\d+:\s+`([^`]+)`\s+\[([^\]]+)\]\s*$", job_body)
        if len(scene_chunks) < 4:
            continue

        rebuilt_scenes: list[dict[str, Any]] = []
        for s_idx in range(1, len(scene_chunks) - 2, 3):
            sc_id = scene_chunks[s_idx].strip()
            sc_kind = scene_chunks[s_idx + 1].strip()
            sc_body = scene_chunks[s_idx + 2]

            base_sc = copy.deepcopy(
                scene_lookup.get(
                    sc_id,
                    {
                        "id": sc_id,
                        "sectionId": sc_id,
                        "sectionLabel": sc_id,
                        "badge": "SECTION",
                        "badgeColor": "blue",
                        "kind": sc_kind,
                        "heading": "",
                        "sub": "",
                        "tip": "",
                        "narration": "",
                    },
                )
            )
            before_snapshot = json.dumps(base_sc, ensure_ascii=False, sort_keys=True)
            base_sc["kind"] = sc_kind

            for field in ("heading", "sub", "tip"):
                m = re.search(rf"(?m)^-\s+\*\*{field}\*\*:\s*(.*)$", sc_body)
                if m is not None:
                    base_sc[field] = m.group(1).strip()

            m_badge = re.search(r"(?m)^-\s+\*\*badge\*\*:\s*(.+?)\s*\(([^)]+)\)\s*$", sc_body)
            if m_badge:
                base_sc["badge"] = m_badge.group(1).strip()
                base_sc["badgeColor"] = m_badge.group(2).strip()

            m_img = re.search(r"(?m)^-\s+\*\*image\*\*:\s*`([^`]+)`", sc_body)
            if m_img:
                base_sc["image"] = m_img.group(1).strip()

            m_vid = re.search(r"(?m)^-\s+\*\*video\*\*:\s*`([^`]+)`", sc_body)
            if m_vid:
                base_sc["video"] = m_vid.group(1).strip()

            # Extract Bullets block
            m_bul = re.search(r"(?ms)^###\s+Bullets\s*\n(.*?)(?=^###\s+Narration|\Z)", sc_body)
            if m_bul:
                bul_lines = [
                    re.sub(r"^[-*]\s+", "", ln.strip())
                    for ln in m_bul.group(1).splitlines()
                    if re.match(r"^[-*]\s+", ln.strip())
                ]
                if bul_lines:
                    base_sc["bullets"] = bul_lines
                elif "bullets" in base_sc and "<!-- 箇条書きなし -->" in m_bul.group(1):
                    base_sc.pop("bullets", None)

            # Extract Narration block
            m_nar = re.search(
                r"(?ms)^###\s+Narration\s*\n(.*?)(?=^###\s+Reading|^---\s*$|\Z)", sc_body
            )
            if m_nar:
                narr_clean = m_nar.group(1).strip()
                if narr_clean:
                    base_sc["narration"] = narr_clean

            # Extract Reading (ひらがな読みベース) block if present
            m_read = re.search(
                r"(?ms)^###\s+Reading[^\n]*\n(.*?)(?=^---\s*$|\Z)", sc_body
            )
            if m_read:
                read_clean = m_read.group(1).strip()
                if read_clean:
                    base_sc["narration_kana"] = read_clean

            after_snapshot = json.dumps(base_sc, ensure_ascii=False, sort_keys=True)
            if before_snapshot != after_snapshot:
                modified_ids.append(f"{job_id}/{sc_id}")

            rebuilt_scenes.append(base_sc)

        if rebuilt_scenes:
            jobs[job_id]["scenes"] = rebuilt_scenes

    return new_spec, modified_ids


# ---------------------------------------------------------------------------
# 3b. All-Hiragana Reading Sheet & Dictionary (`export-readings` ⇄ `import-readings`)
# ---------------------------------------------------------------------------
def apply_hiragana_readings_to_spec(
    spec_data: dict[str, Any], custom_dict: Optional[dict[str, str]] = None
) -> tuple[dict[str, Any], dict[str, str], int]:
    """
    Convert all scenes' `narration` into 100% Hiragana reading base (`narration_kana`)
    using `custom_dict` + contextual rules + CoreFoundation tokenizer.
    Returns (updated_spec, extracted_word_map, updated_scene_count).
    """
    try:
        from .render_course_package import kanji_to_hiragana_sentence
        from .tts_dictionary import (
            _segment_with_dictionary_and_hiragana_instruction,
            normalize_prosody_Japanese_tts,
        )
    except ImportError:
        from render_course_package import kanji_to_hiragana_sentence
        from tts_dictionary import (
            _segment_with_dictionary_and_hiragana_instruction,
            normalize_prosody_Japanese_tts,
        )

    new_spec = copy.deepcopy(spec_data)
    jobs = new_spec.get("jobs", new_spec)
    merged_words: dict[str, str] = dict(custom_dict or {})
    updated_count = 0

    for _jid, jdata in jobs.items():
        for sc in jdata.get("scenes", []):
            narr = (sc.get("narration") or "").strip()
            if not narr:
                continue
            explicit_tts = (sc.get("narration_tts") or sc.get("reading") or "").strip()
            prosody_text, applied_repls = normalize_prosody_Japanese_tts(
                narr, custom_dict=custom_dict, hiragana_instruction=explicit_tts
            )
            sc["narration_prosody"] = prosody_text
            sc["applied_replacements"] = [[k, v] for k, v in applied_repls]
            _hira_cf, wmap = kanji_to_hiragana_sentence(narr, custom_dict=merged_words)
            for k, v in wmap.items():
                if k not in merged_words:
                    merged_words[k] = v
            _p_seg, dict_first_kana, _ = _segment_with_dictionary_and_hiragana_instruction(
                narr, custom_dict=custom_dict, hiragana_instruction=explicit_tts or _hira_cf
            )
            target_hira = dict_first_kana if dict_first_kana else (explicit_tts or _hira_cf)
            if sc.get("narration_kana") != target_hira or sc.get("narration_tts") != target_hira:
                sc["narration_kana"] = target_hira
                sc["narration_tts"] = target_hira
                updated_count += 1

    return new_spec, merged_words, updated_count


def export_readings_sheet(
    spec_data: dict[str, Any], package_dir: Path, out_md: Optional[Path] = None
) -> tuple[Path, Path, dict[str, Any], int]:
    """
    Generate:
      1. `<package_dir>/reading_dict.json` (all Kanji words -> Hiragana readings)
      2. `<package_dir>/reading_sheet.md` (editable table of Kanji -> Hiragana + per-scene full Hiragana script)
      3. Populate `narration_kana` in `spec_data` for every scene.
    """
    try:
        from .render_course_package import load_package_reading_dict
    except ImportError:
        from render_course_package import load_package_reading_dict

    existing_dict = load_package_reading_dict(package_dir)
    updated_spec, word_map, updated_scenes = apply_hiragana_readings_to_spec(spec_data, existing_dict)

    dict_path = package_dir / "reading_dict.json"
    dict_path.write_text(
        json.dumps(
            {
                "_comment": "user_overrides に指定した単語のみが優先上書きされ、通常の漢字はイントネーション保持のため漢字のままTTSへ渡されます。reference_readings はパッケージ内の全漢字の参考読み一覧です。",
                "user_overrides": existing_dict,
                "reference_readings": word_map,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    sheet_path = out_md or (package_dir / "reading_sheet.md")
    lines: list[str] = [
        "# 📖 漢字→ひらがな読み一括指定 ＆ 全文ひらがな台本シート (`reading_sheet.md`)",
        "",
        "> **使い方（あとからひらがなで読み方をすべて変える方法）**:",
        "> 1. **単語単位で一括変更したい場合**: 下の「パート1：漢字→ひらがな読み辞書テーブル」の右列（ひらがな読み）を書き換えるか、新しい行 `| 漢字 | ひらがな |` を追加してください。",
        "> 2. **文脈ごとに全文ひらがなで直接指定したい場合**: 下の「パート2：シーン別・全文ひらがな読み台本」の `### Reading (ひらがな読みベース)` を直接ひらがなで書き換えてください（画面下の青背景キャプション `### Caption (画面下キャプション・漢字表記)` は漢字のまま維持されます）。",
        "> 3. 編集後、以下のコマンド1つで `scenes_spec.json` と `reading_dict.json` に一括反映されます：",
        f">    `python3 {SCRIPT_DIR / 'edit_storyboard.py'} import-readings --package-dir {package_dir}`",
        "",
        "---",
        "",
        "## パート1：漢字・英数字 ➔ ひらがな読み辞書テーブル（パッケージ全出単語）",
        "",
        "| 漢字・単語 (原文) | ひらがな読み (ここを書き換えると全シーンに一括反映) |",
        "| :--- | :--- |",
    ]
    for k, v in word_map.items():
        lines.append(f"| {k} | {v} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## パート2：シーン別・全文ひらがな読み台本 (`narration_kana`)",
            "",
        ]
    )

    jobs = updated_spec.get("jobs", updated_spec)
    for job_id, job_data in jobs.items():
        lines.append(f"# JOB: `{job_id}` — {job_data.get('lessonTitle', '')}")
        lines.append("")
        for idx, sc in enumerate(job_data.get("scenes", [])):
            sc_id = sc.get("id", f"scene-{idx+1:02d}")
            lines.append(f"## Scene {idx+1:02d}: `{sc_id}` — {sc.get('heading', '')}")
            lines.append("")
            lines.append("### Caption (画面下キャプション・漢字表記)")
            lines.append(sc.get("narration", ""))
            lines.append("")
            lines.append("### Reading (ひらがな読みベース)")
            lines.append(sc.get("narration_kana", ""))
            lines.append("")
            lines.append("---")
            lines.append("")

    sheet_path.write_text("\n".join(lines), encoding="utf-8")
    return dict_path, sheet_path, updated_spec, updated_scenes


def import_readings_sheet(
    input_path: Path, package_dir: Path, orig_spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """
    Import edited `reading_sheet.md` (or `reading_dict.json` / CSV / TSV / `漢字=ひらがな` file)
    and update both `<package_dir>/reading_dict.json` and every scene's `narration_kana` in `orig_spec`.
    """
    try:
        from .render_course_package import (
            kanji_to_hiragana_sentence,
            load_package_reading_dict,
            parse_reading_dict_text,
        )
    except ImportError:
        from render_course_package import (
            kanji_to_hiragana_sentence,
            load_package_reading_dict,
            parse_reading_dict_text,
        )

    raw_text = input_path.read_text(encoding="utf-8")
    custom_dict = load_package_reading_dict(package_dir)
    parsed_pairs = parse_reading_dict_text(raw_text)
    custom_dict.update(parsed_pairs)

    # Also parse per-scene explicit `### Reading (ひらがな読みベース)` blocks if input is Markdown
    scene_kana_overrides: dict[str, str] = {}
    scene_caption_overrides: dict[str, str] = {}
    if "## Scene " in raw_text and "### Reading" in raw_text:
        chunks = re.split(r"(?m)^##\s+Scene\s+\d+:\s+`([^`]+)`.*$", raw_text)
        for i in range(1, len(chunks) - 1, 2):
            sc_id = chunks[i].strip()
            body = chunks[i + 1]
            m_cap = re.search(
                r"(?ms)^###\s+Caption[^\n]*\n(.*?)(?=^###\s+Reading|^---\s*$|\Z)", body
            )
            if m_cap and m_cap.group(1).strip():
                scene_caption_overrides[sc_id] = m_cap.group(1).strip()
            m_read = re.search(
                r"(?ms)^###\s+Reading[^\n]*\n(.*?)(?=^---\s*$|\Z)", body
            )
            if m_read and m_read.group(1).strip():
                scene_kana_overrides[sc_id] = m_read.group(1).strip()

    new_spec = copy.deepcopy(orig_spec)
    jobs = new_spec.get("jobs", new_spec)
    modified_scenes: list[str] = []

    for jid, jdata in jobs.items():
        for sc in jdata.get("scenes", []):
            sc_id = sc.get("id", "")
            before_kana = sc.get("narration_kana", "")
            before_narr = sc.get("narration", "")

            if sc_id in scene_caption_overrides:
                sc["narration"] = scene_caption_overrides[sc_id]

            # Compute canonical Hiragana from `narration` + `custom_dict`
            auto_hira, _ = kanji_to_hiragana_sentence(sc.get("narration", ""), custom_dict=custom_dict)

            if sc_id in scene_kana_overrides:
                manual_kana = scene_kana_overrides[sc_id]
                # If the user edited the dictionary table AND didn't touch this scene's Reading line,
                # apply the updated dictionary replacements on top so table edits always take effect.
                for k, v in sorted(custom_dict.items(), key=lambda x: len(x[0]), reverse=True):
                    if k and k in manual_kana:
                        manual_kana = manual_kana.replace(k, v)
                # If manual_kana still matches the old narration_kana before table edits, prefer auto_hira
                if manual_kana == before_kana and auto_hira != before_kana:
                    sc["narration_kana"] = auto_hira
                else:
                    sc["narration_kana"] = manual_kana
            else:
                sc["narration_kana"] = auto_hira

            if sc.get("narration_kana") != before_kana or sc.get("narration") != before_narr:
                modified_scenes.append(f"{jid}/{sc_id}")

    dict_path = package_dir / "reading_dict.json"
    dict_path.write_text(
        json.dumps(
            {
                "_comment": "漢字・英単語のひらがな読み辞書。user_overrides に指定した単語のみが優先上書きされます。",
                "user_overrides": custom_dict,
                "readings": custom_dict,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return new_spec, custom_dict, modified_scenes


def export_audio_check_report(
    package_dir: Path, downloads_dir: str = ""
) -> tuple[Path, Path]:
    """
    Pre-Render Voice & Intonation Check Stage:
    1. Populates `narration_prosody` (Kanji+Kana hybrid script preserving natural Japanese pitch accent
       while converting 5,500+ English/Katakana, counters, and homographs) for every scene.
    2. Exports `<package_dir>/audio_check_sheet.md` showing Caption vs Prosody TTS Script vs Applied Dictionary Rules.
    3. Exports `<package_dir>/audio_preview.html` (and copies to `downloads_dir` with embedded base64 MP3 players)
       so the user can listen to every scene's synthesized voice and edit the audio script BEFORE rendering the video.
    """
    import base64
    from render_course_package import load_package_reading_dict  # noqa: E402
    from tts_dictionary import load_active_prosody_dictionary, load_builtin_dictionary  # noqa: E402

    spec_path = resolve_package_spec_path(package_dir)
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    user_overrides = load_package_reading_dict(package_dir)
    updated_spec, word_map, _ = apply_hiragana_readings_to_spec(spec_data, user_overrides)
    save_spec_with_backup(spec_path, updated_spec)

    builtin_total = len(load_builtin_dictionary())
    builtin_active = len(load_active_prosody_dictionary())

    md_path = package_dir / "audio_check_sheet.md"
    md_lines = [
        "# 🔊 ビデオ生成前・音声化＆イントネーション先行確認シート (`audio_check_sheet.md`)",
        "",
        f"- **内蔵発音辞書**: 全 **{builtin_total:,}語**（アクティブ音声変換 **{builtin_active:,}語** ＋ 一般漢字リファレンス）",
        "- **イントネーション保持方式（Prosody-Preserving Hybrid TTS）**:",
        "  - すべてを平仮名にすると形態素境界・アクセント核が失われイントネーションが崩れるため、**一般的な漢字は漢字のまま残し**、**英単語（カタカナ読み）・助数詞・日付・時刻・同形異音語・難読語のみをピンポイント変換**して合成します。",
        "",
        "---",
        "",
    ]

    jobs = updated_spec.get("jobs", updated_spec)
    html_cards: list[str] = []

    for job_id, job_data in jobs.items():
        md_lines.append(f"# JOB: `{job_id}` — {job_data.get('lessonTitle', '')}")
        md_lines.append("")
        html_cards.append(
            f"<h2 style='margin:24px 0 12px;color:#38bdf8;border-bottom:1px solid #334155;padding-bottom:8px;'>🎬 JOB: {job_id} （全{len(job_data.get('scenes', []))}シーン）</h2>"
        )
        for idx, sc in enumerate(job_data.get("scenes", [])):
            sc_id = sc.get("id", f"scene-{idx+1:02d}")
            narr = sc.get("narration", "")
            prosody = sc.get("narration_prosody", narr)
            repls = sc.get("applied_replacements", [])
            repl_str = " / ".join(f"`{k}` → `{v}`" for k, v in repls) if repls else "（変換なし・そのまま自然な漢字イントネーションで発音）"

            mp3_file = package_dir / "_audio_preview" / job_id / f"{idx:02d}_{sc_id}.mp3"
            audio_tag = "<div style='color:#94a3b8;font-size:12px;'>（音声未生成：`--audio-only` または `audio-check --synth` で生成されます）</div>"
            if mp3_file.exists():
                b64 = base64.b64encode(mp3_file.read_bytes()).decode("ascii")
                audio_tag = f"<audio class='scene-audio' data-job='{job_id}' data-idx='{idx}' controls preload='metadata' style='width:100%;height:38px;' src='data:audio/mpeg;base64,{b64}'></audio>"

            md_lines.extend(
                [
                    f"## Scene {idx+1:02d}: `{sc_id}` — {sc.get('heading', '')}",
                    f"- **内蔵辞書による自動変換**: {repl_str}",
                    f"- **先行音声ファイル**: `_audio_preview/{job_id}/{idx:02d}_{sc_id}.mp3`",
                    "",
                    "### 1. 画面下キャプション (`narration`)",
                    narr,
                    "",
                    "### 2. 実際のTTS音声化スクリプト (`narration_prosody` — イントネーション保持)",
                    prosody,
                    "",
                    "---",
                    "",
                ]
            )

            badges_html = (
                "".join(
                    f"<span style='background:#064e3b;color:#a7f3d0;border:1px solid #059669;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;'>{k} ➔ {v}</span>"
                    for k, v in repls
                )
                if repls
                else "<span style='color:#94a3b8;font-size:11px;'>変換対象なし（漢字イントネーション維持）</span>"
            )
            html_cards.append(
                f"""
                <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:14px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <div style="font-weight:800;color:#38bdf8;font-size:14px;">SCENE {idx+1:02d} — {sc_id} <span style="color:#e2e8f0;font-weight:600;margin-left:8px;">{sc.get('heading','')}</span></div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">{badges_html}</div>
                  </div>
                  <div style="margin-bottom:10px;">{audio_tag}</div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div style="background:#0f172a;padding:10px;border-radius:8px;border:1px solid #334155;">
                      <div style="font-size:11px;font-weight:700;color:#94a3b8;margin-bottom:4px;">📺 画面下キャプション (narration)</div>
                      <div style="font-size:13px;line-height:1.65;white-space:pre-wrap;">{narr}</div>
                    </div>
                    <div style="background:#061816;padding:10px;border-radius:8px;border:1px solid #059669;">
                      <div style="font-size:11px;font-weight:700;color:#6ee7b7;margin-bottom:4px;">🗣️ 実際のTTS音声化原稿 (narration_prosody — 漢字イントネーション保持＋辞書変換済)</div>
                      <div style="font-size:13px;line-height:1.65;color:#d1fae5;white-space:pre-wrap;">{prosody}</div>
                    </div>
                  </div>
                </div>
                """
            )

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🔊 ビデオ生成前・音声化＆イントネーション先行確認プレイヤー ({package_dir.name})</title>
<style>
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif; background:#0f172a; color:#f8fafc; padding:24px; }}
  .top-bar {{ position:sticky; top:0; z-index:20; background:rgba(15,23,42,0.95); backdrop-filter:blur(8px); border:1px solid #38bdf8; border-radius:12px; padding:14px 20px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
  button {{ background:#10b981; color:#022c22; font-weight:800; border:none; border-radius:8px; padding:10px 16px; cursor:pointer; font-size:13px; }}
  button.stop {{ background:#ef4444; color:#fff; }}
</style>
</head>
<body>
  <div class="top-bar">
    <div>
      <div style="font-size:17px;font-weight:800;">🔊 ビデオ生成前・音声化＆イントネーション先行確認スタジオ ({package_dir.name})</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;">内蔵辞書 <b>{builtin_total:,}語</b>（旧版の約25倍）適用済み。漢字を残して自然なイントネーションを保ちつつ、英単語（カタカナ読み）・助数詞・同形異音語のみをピンポイント変換しています。</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
      <button onclick="playAllSequential()">▶️ 全シーンを順番に連続試聴</button>
      <button class="stop" onclick="stopAllAudio()">⏹ 停止</button>
    </div>
  </div>
  {''.join(html_cards)}
<script>
let playingQueue = [];
function stopAllAudio() {{
  playingQueue = [];
  document.querySelectorAll('audio.scene-audio').forEach(a => {{ a.pause(); }});
}}
function playAllSequential() {{
  stopAllAudio();
  const audios = Array.from(document.querySelectorAll('audio.scene-audio'));
  if (!audios.length) return;
  let idx = 0;
  function playNext() {{
    if (idx >= audios.length) return;
    const cur = audios[idx++];
    cur.scrollIntoView({{behavior:'smooth', block:'center'}});
    cur.onended = playNext;
    cur.play();
  }}
  playNext();
}}
</script>
</body>
</html>"""

    html_path = package_dir / "audio_preview.html"
    html_path.write_text(html_content, encoding="utf-8")

    if downloads_dir:
        dl_dir = Path(downloads_dir)
        if dl_dir.exists():
            batch_file = package_dir / "batch.json"
            cid = "course"
            lid = package_dir.name
            if batch_file.exists():
                try:
                    bd = json.loads(batch_file.read_text(encoding="utf-8"))
                    cid = bd.get("courseId") or bd.get("course_id", cid)
                    lid = bd.get("lessonId") or bd.get("lesson_id", lid)
                except Exception as exc:
                    logger.debug("Failed to read batch.json in export_audio_check_report: %s", exc)
            dl_html = dl_dir / f"{cid}_{lid}_audio_preview.html"
            shutil.copy2(html_path, dl_html)

    return html_path, md_path


# ---------------------------------------------------------------------------
# 4. Package Helper Functions (Load, Backup, Save)
# ---------------------------------------------------------------------------
def resolve_package_spec_path(package_dir: Path, scenes_json: str = "") -> Path:
    if scenes_json:
        return Path(scenes_json).resolve()
    pkg_spec = package_dir / "scenes_spec.json"
    if pkg_spec.exists():
        return pkg_spec
    # Auto-compile if missing
    try:
        from .render_course_package import auto_compile_package_to_scenes
    except ImportError:
        from render_course_package import auto_compile_package_to_scenes

    compiled = auto_compile_package_to_scenes(package_dir)
    pkg_spec.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    return pkg_spec


def save_spec_with_backup(spec_path: Path, spec_data: dict[str, Any]) -> Path:
    backup_dir = spec_path.parent / ".storyboard_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"scenes_spec.{ts}.json"
    if spec_path.exists():
        shutil.copy2(spec_path, backup_path)
    spec_path.write_text(json.dumps(spec_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


# ---------------------------------------------------------------------------
# 5. Interactive Local Browser GUI (`serve` mode)
# ---------------------------------------------------------------------------
STUDIO_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Course Video Storyboard & Hiragana Reading Studio (v3.3 Remote-Ready)</title>
<style>
  :root {
    --bg: #0b1020; --panel: #131c33; --border: #26355c; --text: #f1f5f9;
    --muted: #94a3b8; --accent: #38bdf8; --emerald: #10b981; --amber: #f59e0b; --rose: #f43f5e;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif; background: var(--bg); color: var(--text); }
  header { position: sticky; top: 0; z-index: 20; background: rgba(11,16,32,0.95); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
  h1 { margin: 0; font-size: 17px; font-weight: 800; letter-spacing: -0.01em; }
  .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select, input, textarea, button { font-family: inherit; font-size: 13px; border-radius: 8px; border: 1px solid var(--border); background: #0f172a; color: var(--text); padding: 8px 12px; }
  button { cursor: pointer; font-weight: 700; transition: all 0.15s; }
  button.primary { background: var(--accent); color: #020617; border-color: var(--accent); }
  button.emerald { background: var(--emerald); color: #022c22; border-color: var(--emerald); }
  button.amber { background: var(--amber); color: #271202; border-color: var(--amber); }
  button:hover { opacity: 0.9; transform: translateY(-1px); }
  .score-pill { padding: 6px 12px; border-radius: 999px; font-weight: 800; font-size: 12px; background: rgba(16,185,129,0.18); border: 1px solid var(--emerald); color: #6ee7b7; }
  main { max-width: 1320px; margin: 16px auto; padding: 0 16px 80px; display: flex; flex-direction: column; gap: 16px; }
  .job-video-bar { background: #0f172a; border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
  .scene-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 18px; display: grid; grid-template-columns: 280px 1fr; gap: 18px; }
  @media (max-width: 780px) {
    .scene-card { grid-template-columns: 1fr; }
    .scene-meta { border-right: none !important; border-bottom: 1px solid var(--border); padding-right: 0 !important; padding-bottom: 12px; }
    .row2 { grid-template-columns: 1fr !important; }
  }
  .scene-meta { display: flex; flex-direction: column; gap: 10px; border-right: 1px solid var(--border); padding-right: 16px; }
  .scene-num { font-size: 12px; font-weight: 800; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; }
  .thumb { width: 100%; aspect-ratio: 16/9; object-fit: contain; background: #050811; border-radius: 8px; border: 1px solid var(--border); }
  .issue-badge { font-size: 12px; padding: 6px 10px; border-radius: 8px; background: rgba(245,158,11,0.16); border: 1px solid rgba(245,158,11,0.5); color: #fcd34d; line-height: 1.4; }
  .ok-badge { font-size: 12px; padding: 6px 10px; border-radius: 8px; background: rgba(16,185,129,0.14); border: 1px solid rgba(16,185,129,0.4); color: #6ee7b7; }
  .fields { display: flex; flex-direction: column; gap: 10px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  label { font-size: 11px; font-weight: 700; color: var(--muted); display: block; margin-bottom: 4px; text-transform: uppercase; }
  input, textarea { width: 100%; }
  textarea.narr { min-height: 76px; font-size: 14px; line-height: 1.65; border-color: #334155; }
  textarea.kana { min-height: 76px; font-size: 14px; line-height: 1.65; border-color: #059669; background: #061816; color: #d1fae5; }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #022c22; border: 1px solid var(--emerald); color: #a7f3d0; padding: 12px 18px; border-radius: 10px; font-weight: 700; display: none; z-index: 100; box-shadow: 0 12px 30px rgba(0,0,0,0.5); }
  video.preview-player { width: 100%; margin-top: 8px; border-radius: 8px; border: 1px solid var(--accent); }
  .modal-bg { position: fixed; inset: 0; background: rgba(2,6,23,0.82); display: none; align-items: center; justify-content: center; z-index: 50; padding: 20px; }
  .modal { background: var(--panel); border: 1px solid var(--accent); border-radius: 16px; max-width: 820px; width: 100%; padding: 22px; display: flex; flex-direction: column; gap: 14px; max-height: 90vh; overflow-y: auto; }
</style>
</head>
<body>
<header>
  <div>
    <h1>🎬 Video Storyboard & Hiragana Reading Studio <span style="color:var(--accent);font-size:12px;">v3.3 Remote</span></h1>
  </div>
  <div class="toolbar">
    <select id="pkgSelect" onchange="switchPackage()" title="コースパッケージ選択"></select>
    <select id="jobSelect" onchange="loadJob()" title="動画ジョブ選択"></select>
    <span id="scorePill" class="score-pill">診断中...</span>
    <button class="primary" id="importVideoBtn" onclick="openImportVideoModal()">📥 どんな動画でも読み込む (.mp4/.mov)</button>
    <button class="emerald" onclick="openReadingModal()">📖 漢字→ひらがな読み一括インプット</button>
    <button class="amber" onclick="polishAll('deterministic')">✨ 全体文脈を自動推敲</button>
    <button class="primary" onclick="saveAll()">💾 保存</button>
    <button onclick="downloadPortableJson()">⬇️ JSON書き出し</button>
  </div>
</header>
<main>
  <div class="job-video-bar" id="jobVideoBar">
    <div style="display:flex;flex-direction:column;gap:4px;">
      <div style="font-weight:800;font-size:14px;" id="jobTitleLabel">🔊 動画生成前・音声＆イントネーション先行チェック ／ 本編動画マスタリング</div>
      <div style="font-size:12px;color:var(--muted);">① まず「🔊 音声のみ先行生成・試聴」でイントネーションを確認・微調整 ➔ ② OKなら「🚀 本編MP4を生成」で動画化できます（内蔵辞書 9,349語 適用済）。</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <button class="amber" id="synthAudioBtn" onclick="synthJobAudio()">🔊 ① 音声のみ先行生成・試聴 (~5秒)</button>
      <button onclick="playAllSceneAudio()">▶️ 全シーン音声を連続試聴</button>
      <button class="emerald" id="remasterBtn" onclick="remasterCurrentJob()">🚀 ② イントネーション保持で本編MP4を生成 (~15秒)</button>
      <button onclick="toggleJobVideoPlayer()">📺 現在の本編MP4を再生 / DL</button>
    </div>
    <div id="jobVideoPlayerBox" style="width:100%;display:none;margin-top:8px;"></div>
  </div>
  <div id="sceneList" style="display:flex;flex-direction:column;gap:16px;"></div>
</main>
<div id="importVideoModal" class="modal-bg">
  <div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h2 style="margin:0;font-size:17px;">📥 任意の動画ファイル（.mp4 / .mov / .webm）を読み込んで編集</h2>
      <button onclick="closeImportVideoModal()">✕ 閉じる</button>
    </div>
    <div style="font-size:13px;color:var(--muted);line-height:1.5;">
      お手元の動画ファイル（講義動画・画面録画・Zoom録画など）をアップロードするか、Mac上のファイルパスを指定してください。<br>
      自動で <b>①音声文字起こし（Whisper / 字幕抽出）➔ ②シーンごとの映像クリップ＆サムネイル切り出し ➔ ③全文ひらがな読みベース（<code>narration_kana</code>）＆辞書生成</b> を行い、この画面でそのままキャプション・ひらがな読みを編集＆再マスタリングできるようにします。
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;background:#0f172a;padding:14px;border-radius:10px;border:1px solid var(--border);">
      <div>
        <label>① スマホ・PCから動画ファイルを選択してアップロード (.mp4 / .mov / .webm / .m4v)</label>
        <input type="file" id="importVideoFile" accept="video/*,.mp4,.mov,.webm,.m4v,.mkv" style="padding:10px;" />
      </div>
      <div style="text-align:center;color:var(--muted);font-size:12px;">— または —</div>
      <div>
        <label>② Mac上の動画ファイルパス（またはドキュメントパス/URL）を直接指定</label>
        <input type="text" id="importVideoPath" placeholder="例: ~/Downloads/sample.mp4" />
      </div>
      <div>
        <label>動画タイトル（任意・空欄ならファイル名から自動設定）</label>
        <input type="text" id="importVideoTitle" placeholder="例: 新規セミナー動画" />
      </div>
    </div>
    <div id="importVideoStatus" style="font-size:13px;color:#6ee7b7;display:none;"></div>
    <div style="display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;">
      <button onclick="closeImportVideoModal()">キャンセル</button>
      <button class="emerald" id="submitImportBtn" onclick="submitImportVideo()">🚀 動画を読み込んでシーン分解・ひらがな化を開始</button>
    </div>
  </div>
</div>
<div id="readingModal" class="modal-bg">
  <div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h2 style="margin:0;font-size:17px;">📖 漢字 ➔ ひらがな読み 一括インプット・編集シート (`reading_dict.json`)</h2>
      <button onclick="closeReadingModal()">✕ 閉じる</button>
    </div>
    <div style="font-size:13px;color:var(--muted);line-height:1.5;">
      1行に1つ <code>漢字=ひらがな</code>（またはタブ・カンマ区切り）を入力すると、それをベースに<b>全シーンの音声読み上げ用ひらがな原稿（<code>narration_kana</code>）が一括で書き換わります</b>（画面下の青背景キャプションは漢字のまま維持されます）。
    </div>
    <textarea id="readingDictInput" rows="15" style="font-family:monospace;font-size:13px;line-height:1.6;"></textarea>
    <div style="display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;">
      <button onclick="closeReadingModal()">キャンセル</button>
      <button class="emerald" onclick="applyReadingDict()">✓ このひらがな読みをベースに全シーンへ一括反映</button>
    </div>
  </div>
</div>
<div id="toast" class="toast"></div>
<script>
const PORTABLE_DATA = window.__PORTABLE_STUDIO_DATA__ || null;
let PACKAGES = [];
let CURRENT_PKG = "";
let SPEC = null;
let AUDIT = null;
let READING_DICT = {};
let CURRENT_JOB = "";
const KINDS = ["hero","split","fullbleed","grid","table","comparison","steps","callout","quote","kpi","video-clip"];
const URL_TOKEN = new URLSearchParams(window.location.search).get("token") || "";

function apiUrl(path) {
  if (!URL_TOKEN) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}token=${encodeURIComponent(URL_TOKEN)}`;
}

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 4000);
}

async function init() {
  if (PORTABLE_DATA) {
    PACKAGES = Object.keys(PORTABLE_DATA.packages);
    CURRENT_PKG = PACKAGES[0];
    const pkgSel = document.getElementById("pkgSelect");
    pkgSel.innerHTML = PACKAGES.map(p => `<option value="${p}">${p}</option>`).join("");
    document.getElementById("remasterBtn").style.display = "none";
    loadPortablePackage(CURRENT_PKG);
    return;
  }
  const res = await fetch(apiUrl("/api/spec"));
  const data = await res.json();
  PACKAGES = data.packages || [data.current_pkg || "default"];
  CURRENT_PKG = data.current_pkg || PACKAGES[0];
  const pkgSel = document.getElementById("pkgSelect");
  pkgSel.innerHTML = PACKAGES.map(p => `<option value="${p}" ${p===CURRENT_PKG?'selected':''}>${p}</option>`).join("");
  SPEC = data.spec;
  AUDIT = data.audit;
  READING_DICT = data.reading_dict || {};
  populateJobs();
}

function loadPortablePackage(pkgKey) {
  const saved = localStorage.getItem("studio_pkg_" + pkgKey);
  const entry = saved ? JSON.parse(saved) : PORTABLE_DATA.packages[pkgKey];
  SPEC = entry.spec;
  READING_DICT = entry.reading_dict || {};
  AUDIT = entry.audit || {};
  populateJobs();
}

function populateJobs() {
  const jobs = Object.keys(SPEC.jobs || SPEC);
  const sel = document.getElementById("jobSelect");
  sel.innerHTML = jobs.map(j => `<option value="${j}">${j}</option>`).join("");
  CURRENT_JOB = jobs[0];
  document.getElementById("jobVideoPlayerBox").style.display = "none";
  renderScenes();
}

async function switchPackage() {
  CURRENT_PKG = document.getElementById("pkgSelect").value;
  if (PORTABLE_DATA) {
    loadPortablePackage(CURRENT_PKG);
    return;
  }
  const res = await fetch(apiUrl(`/api/spec?pkg=${encodeURIComponent(CURRENT_PKG)}`));
  const data = await res.json();
  SPEC = data.spec;
  AUDIT = data.audit;
  READING_DICT = data.reading_dict || {};
  populateJobs();
}

function loadJob() {
  CURRENT_JOB = document.getElementById("jobSelect").value;
  document.getElementById("jobVideoPlayerBox").style.display = "none";
  renderScenes();
}

function toggleJobVideoPlayer() {
  const box = document.getElementById("jobVideoPlayerBox");
  if (box.style.display === "block") {
    box.style.display = "none";
    return;
  }
  if (PORTABLE_DATA) {
    showToast("ポータブルHTMLモードではJSON書き出し後にMac側で再マスタリングできます");
    return;
  }
  const videoUrl = apiUrl(`/asset/${CURRENT_JOB}/${CURRENT_JOB}.mp4?pkg=${encodeURIComponent(CURRENT_PKG)}&t=${Date.now()}`);
  box.style.display = "block";
  box.innerHTML = `
    <video class="preview-player" style="max-height:420px;background:#000;" controls autoplay src="${videoUrl}"></video>
    <div style="margin-top:6px;text-align:right;">
      <a href="${videoUrl}" download="${CURRENT_PKG.replace(/\\//g,'_')}_${CURRENT_JOB}.mp4" style="color:var(--accent);font-weight:700;font-size:13px;">⬇️ このMP4動画を端末にダウンロード (${CURRENT_JOB}.mp4)</a>
    </div>`;
}

async function remasterCurrentJob() {
  await saveAll();
  const btn = document.getElementById("remasterBtn");
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = `⏳ ${CURRENT_JOB} のTTS音声・MP4を再マスタリング中...`;
  showToast(`⏳ ${CURRENT_JOB} のひらがな読みから音声・MP4を再生成しています...`);
  try {
    const res = await fetch(apiUrl("/api/remaster-job"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`🎉 ${CURRENT_JOB}.mp4 の再マスタリングが完了しました！`);
      const box = document.getElementById("jobVideoPlayerBox");
      const videoUrl = apiUrl(`${data.video_url}&t=${Date.now()}`);
      box.style.display = "block";
      box.innerHTML = `
        <video class="preview-player" style="max-height:420px;background:#000;" controls autoplay src="${videoUrl}"></video>
        <div style="margin-top:6px;text-align:right;">
          <a href="${videoUrl}" download="${CURRENT_PKG.replace(/\\//g,'_')}_${CURRENT_JOB}.mp4" style="color:var(--accent);font-weight:700;font-size:13px;">⬇️ 最新MP4動画を端末にダウンロード (${CURRENT_JOB}.mp4)</a>
        </div>`;
    } else {
      showToast(`❌ エラー: ${data.error}`);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function openReadingModal() {
  const lines = Object.entries(READING_DICT).map(([k, v]) => `${k}=${v}`).join("\\n");
  document.getElementById("readingDictInput").value = lines;
  document.getElementById("readingModal").style.display = "flex";
}

function closeReadingModal() {
  document.getElementById("readingModal").style.display = "none";
}

async function applyReadingDict() {
  const raw = document.getElementById("readingDictInput").value;
  if (PORTABLE_DATA) {
    const pairs = {};
    raw.split("\\n").forEach(ln => {
      const m = ln.trim().split(/[=\\t,→]/);
      if (m.length >= 2 && m[0].trim() && m[1].trim()) pairs[m[0].trim()] = m[1].trim();
    });
    READING_DICT = Object.assign({}, READING_DICT, pairs);
    const sortedKeys = Object.keys(READING_DICT).sort((a,b) => b.length - a.length);
    const jobs = SPEC.jobs || SPEC;
    Object.values(jobs).forEach(j => {
      (j.scenes || []).forEach(sc => {
        let base = sc.narration_kana || sc.narration_tts || sc.narration || "";
        sortedKeys.forEach(k => { base = base.split(k).join(READING_DICT[k]); });
        sc.narration_kana = base;
        if ("narration_tts" in sc) sc.narration_tts = base;
      });
    });
    localStorage.setItem("studio_pkg_" + CURRENT_PKG, JSON.stringify({spec: SPEC, reading_dict: READING_DICT, audit: AUDIT}));
    closeReadingModal();
    renderScenes();
    showToast(`📖 ${sortedKeys.length}語のひらがな読みを全シーンに反映しました（ブラウザ保存済）`);
    return;
  }
  const res = await fetch(apiUrl("/api/readings"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, raw_text: raw, spec: SPEC })
  });
  const data = await res.json();
  SPEC = data.spec;
  READING_DICT = data.reading_dict;
  AUDIT = data.audit;
  closeReadingModal();
  renderScenes();
  showToast(`📖 ${Object.keys(READING_DICT).length}語のひらがな読みをベースに全シーンを更新しました`);
}

function downloadPortableJson() {
  const blob = new Blob([JSON.stringify({ package: CURRENT_PKG, reading_dict: READING_DICT, scenes_spec: SPEC }, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${CURRENT_PKG.replace(/\\//g,'_')}_scenes_and_readings.json`;
  a.click();
}

function renderScenes() {
  const jobs = SPEC.jobs || SPEC;
  const scenes = jobs[CURRENT_JOB].scenes || [];
  const jobAudit = (AUDIT && AUDIT[CURRENT_JOB]) || { score: 100, scenes: [] };
  document.getElementById("scorePill").textContent = `日本語スコア: ${jobAudit.score} / 100 (課題 ${jobAudit.total_issues || 0}件)`;
  document.getElementById("jobTitleLabel").textContent = `📦 ${CURRENT_PKG} ／ 🎬 ${CURRENT_JOB} （全${scenes.length}シーン）`;

  const container = document.getElementById("sceneList");
  container.innerHTML = scenes.map((sc, idx) => {
    const a = (jobAudit.scenes && jobAudit.scenes[idx]) || { issues: [] };
    const issueHtml = a.issues.length
      ? a.issues.map(i => `<div class="issue-badge">⚠️ <b>${i.label}</b><br>${i.suggestion}</div>`).join("")
      : `<div class="ok-badge">✓ 自然な日本語・文脈OK</div>`;
    const imgUrl = (!PORTABLE_DATA && sc.image) ? apiUrl(`/asset/${sc.image.replace(/^\\.\\.\\//,'')}?pkg=${encodeURIComponent(CURRENT_PKG)}`) : "";
    const kindOpts = KINDS.map(k => `<option value="${k}" ${sc.kind===k?'selected':''}>${k}</option>`).join("");
    const bulletsText = (sc.bullets || []).join("\\n");
    return `
      <div class="scene-card" id="card-${idx}">
        <div class="scene-meta">
          <div class="scene-num">SCENE ${String(idx+1).padStart(2,'0')} — ${sc.id}</div>
          ${imgUrl ? `<img class="thumb" src="${imgUrl}" alt="scene thumbnail" onerror="this.style.display='none'">` : ""}
          <div>
            <label>スライド型 (kind)</label>
            <select onchange="updateField(${idx}, 'kind', this.value)">${kindOpts}</select>
          </div>
          ${issueHtml}
          <div id="preview-box-${idx}"></div>
        </div>
        <div class="fields">
          <div class="row2">
            <div>
              <label>見出し (Heading)</label>
              <input value="${escapeHtml(sc.heading||'')}" oninput="updateField(${idx}, 'heading', this.value)">
            </div>
            <div>
              <label>サブ見出し (Sub)</label>
              <input value="${escapeHtml(sc.sub||'')}" oninput="updateField(${idx}, 'sub', this.value)">
            </div>
          </div>
          <div class="row2">
            <div>
              <label>箇条書き (Bullets - 1行1項目)</label>
              <textarea rows="3" oninput="updateBullets(${idx}, this.value)">${escapeHtml(bulletsText)}</textarea>
            </div>
            <div>
              <label>補足ポイント (Tip)</label>
              <textarea rows="3" oninput="updateField(${idx}, 'tip', this.value)">${escapeHtml(sc.tip||'')}</textarea>
            </div>
          </div>
          <div>
            <label>📺 ① 画面下キャプション原稿 (Narration — 画面下の青背景キャプションに表示される漢字かな交じり文)</label>
            <textarea class="narr" id="narr-${idx}" oninput="updateField(${idx}, 'narration', this.value)">${escapeHtml(sc.narration||'')}</textarea>
          </div>
          <div>
            <label style="color:#6ee7b7;">🗣️ ② 音声合成用・イントネーション保持スクリプト (Narration Prosody — 一般漢字の抑揚を保ちつつ英単語・難読漢字・助数詞のみを発音変換。ここを直接編集するとTTS音声に即反映)</label>
            <textarea class="kana" id="prosody-${idx}" oninput="updateField(${idx}, 'narration_prosody', this.value)">${escapeHtml(sc.narration_prosody||sc.narration||'')}</textarea>
            ${(sc.applied_replacements && sc.applied_replacements.length) ? `<div style="margin-top:4px;font-size:11px;color:#fcd34d;">📖 内蔵辞書(9,349語)自動変換: ${sc.applied_replacements.map(p => `<code>${escapeHtml(p[0])}➔${escapeHtml(p[1])}</code>`).join(" ")}</div>` : ""}
          </div>
          <details style="margin-top:2px;">
            <summary style="cursor:pointer;font-size:11px;color:var(--muted);">🔤 ③ 全文ひらがな読み確認用 (Narration Kana — 参考表示)</summary>
            <textarea class="narr" style="min-height:54px;margin-top:6px;font-size:12px;" id="kana-${idx}" oninput="updateField(${idx}, 'narration_kana', this.value)">${escapeHtml(sc.narration_kana||sc.narration_tts||'')}</textarea>
          </details>
          <div style="background:#0f172a;padding:8px 12px;border-radius:8px;border:1px solid var(--border);display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <span style="font-size:12px;font-weight:700;color:#38bdf8;">🔊 先行試聴:</span>
            <audio id="audio-player-${idx}" class="scene-audio-el" controls preload="metadata" style="height:34px;flex:1;min-width:220px;" src="${!PORTABLE_DATA ? apiUrl(`/asset/_audio_preview/${CURRENT_JOB}/${String(idx+1).padStart(2,'0')}_${sc.id}.mp3?pkg=${encodeURIComponent(CURRENT_PKG)}`) : ''}"></audio>
            ${!PORTABLE_DATA ? `<button class="amber" onclick="synthSingleSceneAudio(${idx})">🔄 この1シーンの音声だけ再合成 (~2秒)</button>` : ""}
          </div>
          <div class="actions">
            <button class="amber" onclick="polishOne(${idx})">✨ このシーンの日本語・文脈を自然化</button>
            ${!PORTABLE_DATA ? `<button class="emerald" onclick="renderSingleScene(${idx})">🎬 この1シーンだけ動画プレビュー生成 (~4秒)</button>` : ""}
            <button onclick="moveScene(${idx}, -1)">↑ 上へ</button>
            <button onclick="moveScene(${idx}, 1)">↓ 下へ</button>
          </div>
        </div>
      </div>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function updateField(idx, field, val) {
  const jobs = SPEC.jobs || SPEC;
  jobs[CURRENT_JOB].scenes[idx][field] = val;
  if (field === "narration_kana" && "narration_tts" in jobs[CURRENT_JOB].scenes[idx]) {
    jobs[CURRENT_JOB].scenes[idx].narration_tts = val;
  }
}

function updateBullets(idx, val) {
  const jobs = SPEC.jobs || SPEC;
  const arr = val.split("\\n").map(s => s.trim()).filter(Boolean);
  if (arr.length) jobs[CURRENT_JOB].scenes[idx].bullets = arr;
  else delete jobs[CURRENT_JOB].scenes[idx].bullets;
}

function moveScene(idx, dir) {
  const jobs = SPEC.jobs || SPEC;
  const arr = jobs[CURRENT_JOB].scenes;
  const target = idx + dir;
  if (target < 0 || target >= arr.length) return;
  const tmp = arr[idx];
  arr[idx] = arr[target];
  arr[target] = tmp;
  renderScenes();
}

async function saveAll() {
  if (PORTABLE_DATA) {
    localStorage.setItem("studio_pkg_" + CURRENT_PKG, JSON.stringify({spec: SPEC, reading_dict: READING_DICT, audit: AUDIT}));
    showToast("✓ ブラウザに保存しました（⬇️ JSON書き出しでファイル保存も可能）");
    return;
  }
  const res = await fetch(apiUrl("/api/save"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, spec: SPEC })
  });
  const data = await res.json();
  AUDIT = data.audit;
  renderScenes();
  showToast("✓ scenes_spec.json を保存し、再診断を完了しました");
}

async function polishAll(mode) {
  if (PORTABLE_DATA) {
    showToast("ポータブルモードでは各テキスト欄または📖ひらがな辞書で直接編集できます");
    return;
  }
  const res = await fetch(apiUrl("/api/polish"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB, mode: mode, spec: SPEC })
  });
  const data = await res.json();
  SPEC = data.spec;
  AUDIT = data.audit;
  renderScenes();
  showToast(`✨ ${data.changed_count} シーンの日本語と文脈接続を推敲しました`);
}

async function polishOne(idx) {
  if (PORTABLE_DATA) return;
  const jobs = SPEC.jobs || SPEC;
  const scId = jobs[CURRENT_JOB].scenes[idx].id;
  const res = await fetch(apiUrl("/api/polish"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB, mode: "deterministic", target_scene: scId, spec: SPEC })
  });
  const data = await res.json();
  SPEC = data.spec;
  AUDIT = data.audit;
  renderScenes();
  showToast(`✨ シーン ${scId} を自然化しました`);
}

async function synthJobAudio() {
  if (PORTABLE_DATA) {
    showToast("音声合成はローカル/リモートサーバー接続モードで実行できます");
    return;
  }
  await saveAll();
  const btn = document.getElementById("synthAudioBtn");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = `⏳ ${CURRENT_JOB} の全シーン音声を合成中...`;
  showToast(`⏳ ${CURRENT_JOB} のイントネーション保持TTS音声を先行生成中...`);
  try {
    const res = await fetch(apiUrl("/api/synth-audio"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB })
    });
    const data = await res.json();
    if (data.ok) {
      renderScenes();
      document.querySelectorAll(".scene-audio-el").forEach(a => {
        const base = a.src.split("&t=")[0];
        a.src = `${base}&t=${Date.now()}`;
      });
      showToast(`🔊 ${CURRENT_JOB} の全シーン音声の先行生成が完了しました！各カードまたは連続再生で試聴できます`);
    } else {
      showToast(`❌ 音声合成エラー: ${data.error}`);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function synthSingleSceneAudio(idx) {
  if (PORTABLE_DATA) return;
  await saveAll();
  const jobs = SPEC.jobs || SPEC;
  const scId = jobs[CURRENT_JOB].scenes[idx].id;
  showToast(`⏳ シーン ${scId} の音声のみ再合成中...`);
  const res = await fetch(apiUrl("/api/synth-audio"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB, scene_id: scId })
  });
  const data = await res.json();
  if (data.ok) {
    const audioEl = document.getElementById(`audio-player-${idx}`);
    if (audioEl) {
      audioEl.src = apiUrl(`/asset/_audio_preview/${CURRENT_JOB}/${String(idx+1).padStart(2,'0')}_${scId}.mp3?pkg=${encodeURIComponent(CURRENT_PKG)}&t=${Date.now()}`);
      audioEl.play();
    }
    showToast(`🔊 シーン ${scId} の音声を更新して再生しました`);
  } else {
    showToast(`❌ 音声エラー: ${data.error}`);
  }
}

function playAllSceneAudio() {
  const players = Array.from(document.querySelectorAll(".scene-audio-el"));
  if (!players.length) return;
  let i = 0;
  function next() {
    if (i >= players.length) return;
    const p = players[i++];
    p.scrollIntoView({behavior: "smooth", block: "center"});
    p.onended = next;
    p.onerror = next;
    p.play().catch(next);
  }
  next();
}

async function renderSingleScene(idx) {
  await saveAll();
  const jobs = SPEC.jobs || SPEC;
  const scId = jobs[CURRENT_JOB].scenes[idx].id;
  const box = document.getElementById(`preview-box-${idx}`);
  box.innerHTML = `<div class="issue-badge">⏳ シーン ${scId} を高速レンダリング中...</div>`;
  const res = await fetch(apiUrl("/api/render-scene"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ pkg: CURRENT_PKG, job_id: CURRENT_JOB, scene_id: scId })
  });
  const data = await res.json();
  if (data.ok) {
    box.innerHTML = `<video class="preview-player" controls autoplay src="${apiUrl(data.video_url)}&t=${Date.now()}"></video>`;
    showToast(`🎬 シーン ${scId} のプレビュー動画を生成しました`);
  } else {
    box.innerHTML = `<div class="issue-badge">❌ エラー: ${data.error}</div>`;
  }
}

function openImportVideoModal() {
  if (PORTABLE_DATA) {
    showToast("動画の新規読み込み・文字起こしはサーバー接続モード（ローカル / LAN / HTTPSトンネル）で利用できます");
    return;
  }
  document.getElementById("importVideoStatus").style.display = "none";
  document.getElementById("importVideoModal").style.display = "flex";
}

function closeImportVideoModal() {
  document.getElementById("importVideoModal").style.display = "none";
}

async function submitImportVideo() {
  const fileEl = document.getElementById("importVideoFile");
  const pathVal = document.getElementById("importVideoPath").value.trim();
  const titleVal = document.getElementById("importVideoTitle").value.trim();
  const statusEl = document.getElementById("importVideoStatus");
  const btn = document.getElementById("submitImportBtn");

  if ((!fileEl.files || !fileEl.files[0]) && !pathVal) {
    showToast("動画ファイルを選択するか、ファイルパスを入力してください");
    return;
  }

  btn.disabled = true;
  statusEl.style.display = "block";
  statusEl.textContent = "⏳ 動画を解析・音声文字起こし・シーン分割・ひらがな読みベース生成中...（数十秒かかる場合があります）";

  try {
    let res;
    if (fileEl.files && fileEl.files[0]) {
      const f = fileEl.files[0];
      const q = `filename=${encodeURIComponent(f.name)}&title=${encodeURIComponent(titleVal)}`;
      res = await fetch(apiUrl(`/api/upload-video?${q}`), {
        method: "POST",
        headers: {"Content-Type": "application/octet-stream"},
        body: f
      });
    } else {
      res = await fetch(apiUrl("/api/import-video"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ video_path: pathVal, title: titleVal })
      });
    }
    const data = await res.json();
    if (!data.ok) {
      statusEl.textContent = "❌ 読み込みエラー: " + (data.error || "不明なエラー");
      btn.disabled = false;
      return;
    }
    PACKAGES = data.packages;
    CURRENT_PKG = data.current_pkg;
    const pkgSel = document.getElementById("pkgSelect");
    pkgSel.innerHTML = PACKAGES.map(p => `<option value="${p}" ${p===CURRENT_PKG?'selected':''}>${p}</option>`).join("");
    SPEC = data.spec;
    AUDIT = data.audit;
    READING_DICT = data.reading_dict || {};
    populateJobs();
    closeImportVideoModal();
    showToast(`🎉 動画「${CURRENT_PKG}」を読み込み、全シーンのひらがな読みベースを作成しました！`);
  } catch (e) {
    statusEl.textContent = "❌ 通信エラー: " + e;
  } finally {
    btn.disabled = false;
  }
}

init();
</script>
</body>
</html>
"""


def discover_packages_map(initial_pkg_dir: Path) -> tuple[dict[str, Path], str]:
    """
    Discover sibling course packages so a single remote studio URL can switch between
    all courses (e.g., `ai-user-a01/lesson01`, `ai-user-a02/lesson02`, `ai-user-a03/lesson03`).
    """
    pkg_map: dict[str, Path] = {}
    root_candidates = [initial_pkg_dir, initial_pkg_dir.parent, initial_pkg_dir.parent.parent]
    search_root = initial_pkg_dir
    for cand in root_candidates:
        found = sorted(cand.glob("*/*/batch.json")) or sorted(cand.glob("*/batch.json"))
        if len(found) > 1:
            search_root = cand
            break

    batch_files = sorted(search_root.rglob("batch.json"))
    if not batch_files and (initial_pkg_dir / "batch.json").exists():
        batch_files = [initial_pkg_dir / "batch.json"]

    default_key = ""
    for bf in batch_files:
        pdir = bf.parent.resolve()
        try:
            rel_key = str(pdir.relative_to(search_root))
            if rel_key == ".":
                rel_key = pdir.name
        except ValueError:
            rel_key = pdir.name
        pkg_map[rel_key] = pdir
        if pdir == initial_pkg_dir.resolve():
            default_key = rel_key

    if not pkg_map:
        pkg_map[initial_pkg_dir.name] = initial_pkg_dir.resolve()
        default_key = initial_pkg_dir.name
    elif not default_key:
        default_key = next(iter(pkg_map.keys()))

    return pkg_map, default_key


def export_portable_webapp(package_dir: Path, out_html: Path) -> Path:
    """
    Generate a 100% standalone, zero-server single-file Web Studio HTML (`out_html`)
    embedding all discovered course packages, `scenes_spec.json`, and `reading_dict.json`.
    Can be opened from anywhere (Google Drive, Dropbox, GitHub Pages, Vercel, iPhone/iPad).
    """
    try:
        from .render_course_package import load_package_reading_dict
    except ImportError:
        from render_course_package import load_package_reading_dict

    pkg_map, _ = discover_packages_map(package_dir)
    bundle: dict[str, Any] = {}
    for key, pdir in pkg_map.items():
        sp = resolve_package_spec_path(pdir)
        spec_data = json.loads(sp.read_text(encoding="utf-8"))
        rdict = load_package_reading_dict(pdir)
        spec_data, rdict, _ = apply_hiragana_readings_to_spec(spec_data, rdict)
        jobs = spec_data.get("jobs", spec_data)
        audits = {jid: audit_job_scenes(jdata.get("scenes", [])) for jid, jdata in jobs.items()}
        bundle[key] = {
            "spec": spec_data,
            "reading_dict": rdict,
            "audit": audits,
        }

    inject_script = (
        "<script>window.__PORTABLE_STUDIO_DATA__ = "
        + json.dumps({"packages": bundle}, ensure_ascii=False)
        + ";</script>\n"
    )
    html_out = STUDIO_HTML.replace("<script>", inject_script + "<script>", 1)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html_out, encoding="utf-8")
    return out_html


def _get_lan_ip() -> str:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def run_studio_server(
    package_dir: Path,
    spec_path: Path,
    port: int = 8765,
    host: str = "127.0.0.1",
    tunnel: bool = False,
    token: str = "",
) -> None:
    """
    Start threaded HTTP server for visual manual + AI storyboard & Hiragana reading editing.
    Supports local (`127.0.0.1`), LAN/Wi-Fi (`--host 0.0.0.0`), and internet HTTPS tunnel (`--tunnel` via cloudflared).
    """
    import secrets

    try:
        from .render_course_package import load_package_reading_dict, parse_reading_dict_text
    except ImportError:
        from render_course_package import load_package_reading_dict, parse_reading_dict_text

    pkg_map, default_pkg_key = discover_packages_map(package_dir)
    is_external = (host != "127.0.0.1" and host != "localhost") or tunnel
    auth_token = token.strip() if token else (secrets.token_urlsafe(16) if is_external else "")

    def _resolve_pkg(pkg_key: Optional[str]) -> tuple[str, Path, Path]:
        k = pkg_key if (pkg_key and pkg_key in pkg_map) else default_pkg_key
        pdir = pkg_map[k]
        spath = resolve_package_spec_path(pdir)
        return k, pdir, spath

    def _compute_all_audits(spec_data: dict[str, Any]) -> dict[str, Any]:
        jobs = spec_data.get("jobs", spec_data)
        return {jid: audit_job_scenes(jdata.get("scenes", [])) for jid, jdata in jobs.items()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _check_auth(self, parsed: urllib.parse.ParseResult) -> bool:
            if not auth_token:
                return True
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("token", [""])[0] == auth_token:
                return True
            cookie_hdr = self.headers.get("Cookie", "")
            if f"studio_token={auth_token}" in cookie_hdr:
                return True
            if self.headers.get("X-Studio-Token", "") == auth_token:
                return True
            self.send_response(401)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("401 Unauthorized: Access token required (?token=...).".encode("utf-8"))
            return False

        def _send_json(self, obj: Any, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if not self._check_auth(parsed):
                return
            qs = urllib.parse.parse_qs(parsed.query)
            pkg_req = qs.get("pkg", [None])[0]

            if parsed.path == "/":
                body = STUDIO_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                if auth_token:
                    self.send_header("Set-Cookie", f"studio_token={auth_token}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/spec":
                cur_key, pdir, spath = _resolve_pkg(pkg_req)
                spec_data = json.loads(spath.read_text(encoding="utf-8"))
                rdict = load_package_reading_dict(pdir)
                spec_data, rdict, _ = apply_hiragana_readings_to_spec(spec_data, rdict)
                self._send_json(
                    {
                        "packages": list(pkg_map.keys()),
                        "current_pkg": cur_key,
                        "spec": spec_data,
                        "audit": _compute_all_audits(spec_data),
                        "reading_dict": rdict,
                    }
                )
                return
            if parsed.path.startswith("/asset/"):
                _, pdir, _ = _resolve_pkg(pkg_req)
                rel = urllib.parse.unquote(parsed.path[len("/asset/") :].lstrip("/"))
                cand = (pdir / rel).resolve()
                # Strict path traversal protection for external access
                if not str(cand).startswith(str(pdir.resolve())):
                    self.send_error(403)
                    return
                if cand.exists() and cand.is_file():
                    data = cand.read_bytes()
                    suf = cand.suffix.lower()
                    if suf == ".mp4":
                        ctype = "video/mp4"
                    elif suf == ".mp3":
                        ctype = "audio/mpeg"
                    elif suf == ".wav":
                        ctype = "audio/wav"
                    elif suf == ".html":
                        ctype = "text/html; charset=utf-8"
                    else:
                        ctype = "image/png"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_error(404)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if not self._check_auth(parsed):
                return
            length = int(self.headers.get("Content-Length", "0"))

            if parsed.path == "/api/upload-video":
                qs = urllib.parse.parse_qs(parsed.query)
                fname = Path(qs.get("filename", ["uploaded_video.mp4"])[0]).name
                title_arg = qs.get("title", [""])[0].strip()
                raw_bytes = self.rfile.read(length) if length > 0 else b""
                if not raw_bytes:
                    self._send_json({"ok": False, "error": "Empty video upload"}, status=400)
                    return
                try:
                    try:
                        from .compile_input_to_spec import _slug, build_package
                    except ImportError:
                        from compile_input_to_spec import _slug, build_package

                    upload_root = package_dir / "imported_videos"
                    upload_root.mkdir(parents=True, exist_ok=True)
                    src_file = upload_root / fname
                    src_file.write_bytes(raw_bytes)
                    slug = _slug(src_file.stem, fname)
                    out_pkg = upload_root / slug
                    build_package(str(src_file), out_dir=out_pkg, title=title_arg or None)
                    rel_key = f"imported_videos/{slug}"
                    pkg_map[rel_key] = out_pkg.resolve()
                    sp = resolve_package_spec_path(out_pkg)
                    spec_data = json.loads(sp.read_text(encoding="utf-8"))
                    rdict = load_package_reading_dict(out_pkg)
                    spec_data, rdict, _ = apply_hiragana_readings_to_spec(spec_data, rdict)
                    self._send_json(
                        {
                            "ok": True,
                            "packages": list(pkg_map.keys()),
                            "current_pkg": rel_key,
                            "spec": spec_data,
                            "audit": _compute_all_audits(spec_data),
                            "reading_dict": rdict,
                        }
                    )
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=500)
                return

            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

            if parsed.path == "/api/import-video":
                video_path_str = str(payload.get("video_path", "")).strip()
                title_arg = str(payload.get("title", "")).strip()
                if not video_path_str:
                    self._send_json({"ok": False, "error": "video_path is required"}, status=400)
                    return
                try:
                    try:
                        from .compile_input_to_spec import _slug, build_package
                    except ImportError:
                        from compile_input_to_spec import _slug, build_package

                    stem_name = Path(video_path_str).stem or "video"
                    slug = _slug(stem_name, video_path_str)
                    out_pkg = package_dir / "imported_videos" / slug
                    build_package(video_path_str, out_dir=out_pkg, title=title_arg or None)
                    rel_key = f"imported_videos/{slug}"
                    pkg_map[rel_key] = out_pkg.resolve()
                    sp = resolve_package_spec_path(out_pkg)
                    spec_data = json.loads(sp.read_text(encoding="utf-8"))
                    rdict = load_package_reading_dict(out_pkg)
                    spec_data, rdict, _ = apply_hiragana_readings_to_spec(spec_data, rdict)
                    self._send_json(
                        {
                            "ok": True,
                            "packages": list(pkg_map.keys()),
                            "current_pkg": rel_key,
                            "spec": spec_data,
                            "audit": _compute_all_audits(spec_data),
                            "reading_dict": rdict,
                        }
                    )
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=500)
                return

            _, pdir, spath = _resolve_pkg(payload.get("pkg"))

            if parsed.path == "/api/save":
                spec_data = payload["spec"]
                save_spec_with_backup(spath, spec_data)
                self._send_json({"ok": True, "audit": _compute_all_audits(spec_data)})
                return

            if parsed.path == "/api/readings":
                spec_data = payload.get("spec") or json.loads(spath.read_text(encoding="utf-8"))
                raw_text = payload.get("raw_text", "")
                new_pairs = parse_reading_dict_text(raw_text)
                updated_spec, merged_dict, _ = apply_hiragana_readings_to_spec(spec_data, new_pairs)
                (pdir / "reading_dict.json").write_text(
                    json.dumps({"readings": merged_dict}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                save_spec_with_backup(spath, updated_spec)
                self._send_json(
                    {
                        "ok": True,
                        "spec": updated_spec,
                        "reading_dict": merged_dict,
                        "audit": _compute_all_audits(updated_spec),
                    }
                )
                return

            if parsed.path == "/api/polish":
                spec_data = payload.get("spec") or json.loads(spath.read_text(encoding="utf-8"))
                job_id = payload["job_id"]
                mode = payload.get("mode", "deterministic")
                target_scene = payload.get("target_scene")
                jobs = spec_data.get("jobs", spec_data)
                scenes = jobs[job_id]["scenes"]
                polished, changes = polish_spec_scenes(scenes, mode=mode, target_scene=target_scene)
                jobs[job_id]["scenes"] = polished
                save_spec_with_backup(spath, spec_data)
                self._send_json(
                    {
                        "ok": True,
                        "spec": spec_data,
                        "changed_count": len(changes),
                        "changes": changes,
                        "audit": _compute_all_audits(spec_data),
                    }
                )
                return

            if parsed.path == "/api/synth-audio":
                cur_key, pdir, spath = _resolve_pkg(payload.get("pkg"))
                job_id = payload["job_id"]
                scene_id = payload.get("scene_id", "")
                cmd = [
                    sys.executable,
                    str(SCRIPT_DIR / "render_course_package.py"),
                    "--package-dir",
                    str(pdir),
                    "--scenes-json",
                    str(spath),
                    "--job",
                    job_id,
                    "--audio-only",
                    "--downloads-dir",
                    "",
                ]
                if scene_id:
                    cmd.extend(["--only-scene", scene_id])
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    self._send_json(
                        {
                            "ok": True,
                            "audio_preview_html": f"/asset/audio_preview.html?pkg={urllib.parse.quote(cur_key)}",
                        }
                    )
                else:
                    self._send_json(
                        {"ok": False, "error": (proc.stderr or proc.stdout)[-400:]}, status=500
                    )
                return

            if parsed.path == "/api/remaster-job":
                cur_key, pdir, spath = _resolve_pkg(payload.get("pkg"))
                job_id = payload["job_id"]
                cmd = [
                    sys.executable,
                    str(SCRIPT_DIR / "render_course_package.py"),
                    "--package-dir",
                    str(pdir),
                    "--scenes-json",
                    str(spath),
                    "--job",
                    job_id,
                    "--reuse-silent-video",
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                mp4_rel = f"{job_id}/{job_id}.mp4"
                if proc.returncode == 0 and (pdir / mp4_rel).exists():
                    self._send_json(
                        {
                            "ok": True,
                            "video_url": f"/asset/{mp4_rel}?pkg={urllib.parse.quote(cur_key)}",
                        }
                    )
                else:
                    self._send_json(
                        {"ok": False, "error": (proc.stderr or proc.stdout)[-400:]}, status=500
                    )
                return

            if parsed.path == "/api/render-scene":
                cur_key, pdir, spath = _resolve_pkg(payload.get("pkg"))
                job_id = payload["job_id"]
                scene_id = payload["scene_id"]
                cmd = [
                    sys.executable,
                    str(SCRIPT_DIR / "render_course_package.py"),
                    "--package-dir",
                    str(pdir),
                    "--scenes-json",
                    str(spath),
                    "--job",
                    job_id,
                    "--only-scene",
                    scene_id,
                    "--downloads-dir",
                    "",
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                preview_rel = f"_scene_previews/{job_id}_{scene_id}.mp4"
                if proc.returncode == 0 and (pdir / preview_rel).exists():
                    self._send_json(
                        {
                            "ok": True,
                            "video_url": f"/asset/{preview_rel}?pkg={urllib.parse.quote(cur_key)}",
                        }
                    )
                else:
                    self._send_json(
                        {"ok": False, "error": (proc.stderr or proc.stdout)[-400:]}, status=500
                    )
                return

            self.send_error(404)

    server = ThreadingHTTPServer((host, port), Handler)
    token_q = f"/?token={auth_token}" if auth_token else ""
    lan_ip = _get_lan_ip()
    print(f"🚀 Storyboard & Hiragana Reading Studio (v3.3) running!")
    print(f"   Local URL       : http://127.0.0.1:{port}{token_q}")
    if host == "0.0.0.0":
        print(f"   LAN / Wi-Fi URL : http://{lan_ip}:{port}{token_q}")
    print(f"   Loaded Packages : {', '.join(pkg_map.keys())}")

    tunnel_proc: Optional[subprocess.Popen[str]] = None
    if tunnel:
        cf_bin = shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
        if Path(cf_bin).exists():
            print("🌐 Starting Cloudflare HTTPS Tunnel (cloudflared)...")
            tunnel_proc = subprocess.Popen(
                [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            start_t = time.time()
            public_url = ""
            while time.time() - start_t < 15 and tunnel_proc.stdout:
                line = tunnel_proc.stdout.readline()
                if not line:
                    break
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    public_url = m.group(0)
                    break
            if public_url:
                print(f"   🌍 External HTTPS URL (スマホ・外出先からアクセス可能):")
                print(f"      {public_url}{token_q}")
            else:
                print("   ⚠️ Could not parse trycloudflare URL within 15s (tunnel still running in background).")
            import threading

            def _drain_pipe(pipe: Any) -> None:
                try:
                    for _ in pipe:
                        pass
                except Exception as exc:
                    logger.debug("Pipe drain finished: %s", exc)

            if tunnel_proc.stdout:
                threading.Thread(target=_drain_pipe, args=(tunnel_proc.stdout,), daemon=True).start()
        else:
            print("   ⚠️ cloudflared not found; install with `brew install cloudflared` for HTTPS tunnel.")

    print("   Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if tunnel_proc:
            tunnel_proc.terminate()


# ---------------------------------------------------------------------------
# 6. CLI Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-Generation Manual & AI Storyboard / Hiragana Reading Editor"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in (
        "audio-check",
        "audit",
        "polish",
        "export-md",
        "import-md",
        "export-readings",
        "import-readings",
        "set-reading",
        "set-scene",
        "import-video",
        "export-webapp",
        "serve",
        "undo",
    ):
        p = sub.add_parser(name)
        p.add_argument("--package-dir", required=True, help="Path to lesson package directory (or parent root directory)")
        p.add_argument("--scenes-json", default="", help="Optional path to scenes_spec.json")
        if name == "audio-check":
            p.add_argument("--job", default="", help="Optional jobId filter")
            p.add_argument("--synth", action="store_true", help="Synthesize TTS audio (--audio-only) before generating audio_preview.html")
            p.add_argument("--downloads-dir", default=str(Path.home() / "Downloads"), help="Also copy audio_preview.html to Downloads")
        if name == "import-video":
            p.add_argument("--video", required=True, help="Path to any video file (.mp4/.mov/.webm/.m4v/.mkv) to ingest")
            p.add_argument("--title", default="", help="Optional video title")
        if name in ("audit", "polish", "set-scene", "set-reading"):
            p.add_argument("--job", default="", help="Optional jobId filter")
        if name == "polish":
            p.add_argument(
                "--mode",
                default="deterministic",
                choices=["deterministic", "llm"],
                help="Polishing engine: deterministic (0-token fact-safe) or llm (holistic LLM + fact gate)",
            )
            p.add_argument("--scene", default="", help="Optional scene ID or 1-based index to polish")
            p.add_argument("--instruction", default="", help="Custom instruction when using --mode llm")
            p.add_argument("--dry-run", action="store_true", help="Preview diffs without writing changes")
        if name in ("export-md", "import-md"):
            p.add_argument("--md", default="", help="Path to storyboard.md (default: <package-dir>/storyboard.md)")
        if name == "export-readings":
            p.add_argument("--out", default="", help="Path to reading_sheet.md (default: <package-dir>/reading_sheet.md)")
        if name == "import-readings":
            p.add_argument(
                "--file",
                default="",
                help="Path to edited reading_sheet.md, reading_dict.json, CSV/TSV, or key=value text (default: <package-dir>/reading_sheet.md)",
            )
        if name == "set-reading":
            p.add_argument(
                "--readings",
                default="",
                help="Comma or newline separated Kanji=Hiragana pairs (e.g. '一言=ひとこと,表にして=ひょうにして,一行=いちぎょう')",
            )
            p.add_argument("--scene", default="", help="Optional scene ID or 1-based index for direct full-Hiragana override")
            p.add_argument("--kana", default=None, help="Full-Hiragana reading script (`narration_kana`) for --scene")
        if name == "set-scene":
            p.add_argument("--scene", required=True, help="Scene ID (e.g. a1-h3-trial-001) or 1-based index (e.g. 1)")
            p.add_argument("--heading", default=None, help="New slide heading")
            p.add_argument("--sub", default=None, help="New slide sub-heading")
            p.add_argument("--tip", default=None, help="New slide tip")
            p.add_argument("--narration", default=None, help="New Japanese narration (shown in bottom caption)")
            p.add_argument("--narration-kana", default=None, help="New full-Hiragana reading base (spoken by TTS)")
            p.add_argument("--kind", default=None, help="New slide layout kind")
            p.add_argument("--bullets", default=None, help="Pipe-separated bullets (e.g. '項目1|項目2|項目3')")
        if name == "export-webapp":
            p.add_argument(
                "--out",
                default="",
                help="Output standalone HTML file path (default: <package-dir>/studio_portable.html)",
            )
        if name == "serve":
            p.add_argument("--port", type=int, default=8765, help="Local port (default: 8765)")
            p.add_argument(
                "--host",
                default="127.0.0.1",
                help="Bind address: '127.0.0.1' (local only) or '0.0.0.0' (LAN / Wi-Fi access)",
            )
            p.add_argument(
                "--tunnel",
                action="store_true",
                help="Automatically open an external HTTPS tunnel via cloudflared (accessible from anywhere outside)",
            )
            p.add_argument(
                "--token",
                default="",
                help="Access token for external authentication (auto-generated when --host 0.0.0.0 or --tunnel is used)",
            )

    args = parser.parse_args()
    package_dir = Path(args.package_dir).resolve()
    if args.cmd == "audio-check":
        if args.synth:
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "render_course_package.py"),
                "--package-dir",
                str(package_dir),
                "--audio-only",
                "--downloads-dir",
                args.downloads_dir,
            ]
            if args.scenes_json:
                cmd.extend(["--scenes-json", args.scenes_json])
            if args.job:
                cmd.extend(["--job", args.job])
            subprocess.run(cmd, check=True)
        html_p, md_p = export_audio_check_report(package_dir, downloads_dir=args.downloads_dir)
        print(f"✓ Generated Pre-Render Audio Check Sheet (Markdown) -> {md_p}")
        print(f"✓ Generated Pre-Render Audio Player HTML            -> {html_p}")
        return

    if args.cmd == "import-video":
        try:
            from .compile_input_to_spec import _slug, build_package
        except ImportError:
            from compile_input_to_spec import _slug, build_package

        vid_p = Path(args.video).expanduser().resolve()
        slug = _slug(vid_p.stem, str(vid_p))
        out_pkg = (package_dir / "imported_videos" / slug) if (package_dir / "ai-user-a01").exists() else package_dir
        built = build_package(str(vid_p), out_dir=out_pkg, title=args.title or None)
        print(f"✓ Imported video into editable package -> {built}")
        return
    if args.cmd == "export-webapp":
        out_html = Path(args.out).resolve() if args.out else (package_dir / "studio_portable.html")
        export_portable_webapp(package_dir, out_html)
        print(f"✓ Exported standalone portable Web Studio HTML -> {out_html}")
        return
    if args.cmd == "serve":
        pkg_map, default_key = discover_packages_map(package_dir)
        first_pkg = pkg_map[default_key]
        spec_path = resolve_package_spec_path(first_pkg, getattr(args, "scenes_json", ""))
        run_studio_server(
            package_dir,
            spec_path,
            port=args.port,
            host=args.host,
            tunnel=args.tunnel,
            token=args.token,
        )
        return
    spec_path = resolve_package_spec_path(package_dir, getattr(args, "scenes_json", ""))
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    jobs = spec_data.get("jobs", spec_data)

    if args.cmd == "audit":
        for jid, jdata in jobs.items():
            if args.job and jid != args.job:
                continue
            rep = audit_job_scenes(jdata.get("scenes", []))
            print(f"=== [{jid}] 日本語自然度・全体文脈スコア: {rep['score']} / 100 "
                  f"(全{rep['scene_count']}シーン / 検出課題 {rep['total_issues']}件) ===")
            s = rep["summary"]
            print(
                f"  内訳: AI常套句={s['ai_cliches']} | 無駄リピート={s.get('redundant_repeats', 0)} | "
                f"冒頭重複={s['repetitive_openings']} | 文末単調={s['monotonous_endings']} | "
                f"長文息継ぎ={s['long_sentences']} | スライド丸読み={s['slide_reading_overlap']}"
            )
            for sc_rep in rep["scenes"]:
                if sc_rep["issues"]:
                    print(f"  - [{sc_rep['index']:02d}] {sc_rep['id']} ({sc_rep['kind']}): {sc_rep['heading']}")
                    for iss in sc_rep["issues"]:
                        print(f"      ⚠️  {iss['label']} -> {iss['suggestion']}")
        return

    if args.cmd == "polish":
        total_changes = 0
        for jid, jdata in jobs.items():
            if args.job and jid != args.job:
                continue
            scenes = jdata.get("scenes", [])
            before_audit = audit_job_scenes(scenes)
            polished, changes = polish_spec_scenes(
                scenes,
                mode=args.mode,
                instruction=args.instruction,
                target_scene=args.scene or None,
            )
            after_audit = audit_job_scenes(polished)
            print(
                f"=== [{jid}] 文脈・日本語推敲 ({args.mode}): "
                f"スコア {before_audit['score']} -> {after_audit['score']} / 100 "
                f"(変更 {len(changes)} シーン) ==="
            )
            for ch in changes:
                print(f"  ✨ [{ch['index']:02d}] {ch['id']}: {', '.join(ch['changes'])}")
                print(f"      Before: {ch['before_narration']}")
                print(f"      After : {ch['after_narration']}")
            jdata["scenes"] = polished
            total_changes += len(changes)

        if not args.dry_run and total_changes > 0:
            bkp = save_spec_with_backup(spec_path, spec_data)
            print(f"\n✓ Saved updated spec to {spec_path} (Backup: {bkp})")
        elif args.dry_run:
            print("\n(Dry-run mode: no files modified)")
        return

    if args.cmd == "export-md":
        try:
            from .render_course_package import load_package_reading_dict
        except ImportError:
            from render_course_package import load_package_reading_dict

        md_out = Path(args.md).resolve() if args.md else (package_dir / "storyboard.md")
        export_spec_to_markdown(spec_data, md_out, custom_dict=load_package_reading_dict(package_dir))
        print(f"✓ Exported editable Markdown storyboard (with Hiragana readings) -> {md_out}")
        return

    if args.cmd == "import-md":
        md_in = Path(args.md).resolve() if args.md else (package_dir / "storyboard.md")
        if not md_in.exists():
            raise FileNotFoundError(f"Storyboard Markdown not found: {md_in}")
        new_spec, mod_ids = import_markdown_to_spec(md_in, spec_data)
        bkp = save_spec_with_backup(spec_path, new_spec)
        print(f"✓ Imported {md_in} -> {spec_path} (Modified scenes: {len(mod_ids)}, Backup: {bkp})")
        for m in mod_ids:
            print(f"  - Updated: {m}")
        return

    if args.cmd == "export-readings":
        out_md = Path(args.out).resolve() if args.out else None
        dict_path, sheet_path, updated_spec, updated_scenes = export_readings_sheet(
            spec_data, package_dir, out_md=out_md
        )
        bkp = save_spec_with_backup(spec_path, updated_spec)
        word_count = len(json.loads(dict_path.read_text(encoding="utf-8")).get("readings", {}))
        print(f"✓ Exported Kanji->Hiragana dictionary ({word_count} words) -> {dict_path}")
        print(f"✓ Exported full-Hiragana reading sheet -> {sheet_path}")
        print(f"✓ Populated `narration_kana` in {spec_path} ({updated_scenes} scenes updated, Backup: {bkp})")
        return

    if args.cmd == "import-readings":
        in_path = Path(args.file).resolve() if args.file else (package_dir / "reading_sheet.md")
        if not in_path.exists():
            alt = package_dir / "reading_dict.json"
            if alt.exists():
                in_path = alt
            else:
                raise FileNotFoundError(f"Reading input file not found: {in_path}")
        new_spec, merged_dict, mod_scenes = import_readings_sheet(in_path, package_dir, spec_data)
        bkp = save_spec_with_backup(spec_path, new_spec)
        print(
            f"✓ Imported Hiragana readings from {in_path} -> {spec_path} "
            f"(Dictionary: {len(merged_dict)} words, Updated scenes: {len(mod_scenes)}, Backup: {bkp})"
        )
        for m in mod_scenes[:20]:
            print(f"  - Updated narration_kana: {m}")
        if len(mod_scenes) > 20:
            print(f"  ... and {len(mod_scenes) - 20} more scenes")
        return

    if args.cmd == "set-reading":
        try:
            from .render_course_package import load_package_reading_dict, parse_reading_dict_text
        except ImportError:
            from render_course_package import load_package_reading_dict, parse_reading_dict_text

        rdict = load_package_reading_dict(package_dir)
        if args.readings:
            normalized_input = args.readings.replace("、", "\n").replace(",", "\n")
            new_pairs = parse_reading_dict_text(normalized_input)
            rdict.update(new_pairs)
            spec_data, rdict, upd_cnt = apply_hiragana_readings_to_spec(spec_data, rdict)
            (package_dir / "reading_dict.json").write_text(
                json.dumps({"readings": rdict}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"✓ Applied {len(new_pairs)} Kanji->Hiragana overrides across {upd_cnt} scenes: {new_pairs}")
        if args.scene and args.kana is not None:
            matched = 0
            for jid, jdata in jobs.items():
                if args.job and jid != args.job:
                    continue
                for idx, sc in enumerate(jdata.get("scenes", [])):
                    if sc.get("id") == args.scene or str(idx + 1) == str(args.scene):
                        sc["narration_kana"] = args.kana.strip()
                        matched += 1
                        print(f"✓ Set full-Hiragana reading (`narration_kana`) for [{jid}] {sc.get('id')}")
            if matched == 0:
                raise ValueError(f"Scene '{args.scene}' not found")
        bkp = save_spec_with_backup(spec_path, spec_data)
        print(f"✓ Saved {spec_path} (Backup: {bkp})")
        return

    if args.cmd == "set-scene":
        matched = 0
        for jid, jdata in jobs.items():
            if args.job and jid != args.job:
                continue
            for idx, sc in enumerate(jdata.get("scenes", [])):
                if sc.get("id") == args.scene or str(idx + 1) == str(args.scene):
                    if args.heading is not None:
                        sc["heading"] = args.heading
                    if args.sub is not None:
                        sc["sub"] = args.sub
                    if args.tip is not None:
                        sc["tip"] = args.tip
                    if args.narration is not None:
                        sc["narration"] = args.narration
                    if args.narration_kana is not None:
                        sc["narration_kana"] = args.narration_kana
                    if args.kind is not None:
                        sc["kind"] = args.kind
                    if args.bullets is not None:
                        sc["bullets"] = [b.strip() for b in args.bullets.split("|") if b.strip()]
                    matched += 1
                    print(f"✓ Updated [{jid}] scene #{idx+1} ({sc.get('id')})")
        if matched == 0:
            raise ValueError(f"Scene '{args.scene}' not found")
        bkp = save_spec_with_backup(spec_path, spec_data)
        print(f"✓ Saved {spec_path} (Backup: {bkp})")
        return

    if args.cmd == "undo":
        backup_dir = spec_path.parent / ".storyboard_backups"
        backups = sorted(backup_dir.glob("scenes_spec.*.json")) if backup_dir.exists() else []
        if not backups:
            print("No backups found.")
            return
        latest = backups[-1]
        shutil.copy2(latest, spec_path)
        latest.unlink()
        print(f"✓ Restored {spec_path} from {latest}")
        return

    if args.cmd == "serve":
        run_studio_server(package_dir, spec_path, port=args.port)


if __name__ == "__main__":
    main()
