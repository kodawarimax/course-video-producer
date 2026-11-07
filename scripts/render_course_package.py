#!/usr/bin/env python3
"""
One-Command Deterministic Course Video Producer Pipeline (TokenZero / Formula-First)
Designed so even lower-tier AI models (Gemini 3.8 Flash Low/Medium, Haiku, etc.) can
generate 100% textbook-faithful, broadcast-grade MP4 videos in a single command:

  # existing lesson package (batch.json + scenes_spec.json)
  python3 scripts/render_course_package.py --package-dir "<lesson_package>"

  # any document: Markdown / PDF / PowerPoint / Word / HTML / URL (v3.0)
  python3 scripts/render_course_package.py --input "slides.pptx" --aspect 9:16 --theme sakura

Key Features:
1. Zero-LLM Auto-Compilation:
   - `--input` converts Markdown / PDF / PPTX / DOCX / HTML / URL into a standard package
     via `scripts/compile_input_to_spec.py` (microsoft/markitdown + poppler + LibreOffice).
   - Otherwise resolves `scenes_spec.json` (explicit / package / examples / auto-compiler).
2. Unified Default Voice (`ca8c24e05b1245c4bdbf28bfb9be5275`) with portable fallback:
   - Fish Audio `s2-pro` (env var or macOS Keychain) -> edge-tts -> macOS `say` (`--tts auto`).
3. Parallel TTS Synthesis with SHA-256 content+provider+voice caching.
4. Multi-aspect (16:9 / 9:16 / 1:1), brand themes, and `video-clip` scenes (OffthreadVideo).
5. Broadcast mastering: EBU R128 -14.5 LUFS 48kHz, BT.709 tags, Japanese soft subtitles.

Environment overrides (portability):
  COURSE_VIDEO_REMOTION_ROOT   Remotion project dir (must contain node_modules)
  COURSE_VIDEO_DOWNLOADS_DIR   Default copy/ZIP destination (default: ~/Downloads)
  FISHAUDIO_API_KEY            Fish Audio key (macOS Keychain 'FishAudio' also supported)
  COURSE_VIDEO_EDGE_VOICE      edge-tts voice (default: ja-JP-NanamiNeural)
  COURSE_VIDEO_SAY_VOICE       macOS say voice (default: Kyoko)
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("course_video_producer")

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REPO_REMOTION = SKILL_ROOT / "remotion"
LEGACY_REMOTION = Path.home() / "Claude" / "content" / "video"


def _resolve_remotion_root() -> Path:
    """env -> bundled remotion/ (if npm-installed) -> legacy local engine."""
    env_root = os.environ.get("COURSE_VIDEO_REMOTION_ROOT")
    candidates = [Path(env_root).expanduser()] if env_root else []
    candidates += [REPO_REMOTION, LEGACY_REMOTION]
    for c in candidates:
        if (c / "node_modules" / "@remotion" / "cli").exists():
            return c.resolve()
    # Fall back to bundled dir so the error message points users to `npm install`.
    return REPO_REMOTION


REMOTION_ROOT = _resolve_remotion_root()
PUBLIC_DIR = REMOTION_ROOT / "public"
SCENES_OUT_DIR = REMOTION_ROOT / "src" / "scenes" / "lesson01"
DEFAULT_DOWNLOADS_DIR = os.environ.get(
    "COURSE_VIDEO_DOWNLOADS_DIR", str(Path.home() / "Downloads")
)
ASPECT_PRESETS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
THEME_CHOICES = ("corporate-blue", "warm-academy", "emerald-fresh", "sakura", "mono-minimal")
EDGE_VOICE = os.environ.get("COURSE_VIDEO_EDGE_VOICE", "ja-JP-NanamiNeural")
SAY_VOICE = os.environ.get("COURSE_VIDEO_SAY_VOICE", "Kyoko")

# Unified Default Voice: sample_hybrid_1.mp3
# 「プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー）」(Fish Audio s2-pro / 商用・著作権フリー)
DEFAULT_VOICE_ID = "ca8c24e05b1245c4bdbf28bfb9be5275"
DEFAULT_MODEL = "s2-pro"
FPS = 30
GAP_SEC = 0.45

# Replace ASCII/English acronyms and known Japanese homographs/polyphones (同形異音語)
# that TTS frequently misreads (e.g. 一言->ひとこと, 表->ひょう, 一行->いちぎょう, 人向け->ひとむけ, 元の->もとの).
S2_PRO_SAFE_REPLACEMENTS = [
    ("U-AI初級", "ユーエーアイしょきゅう"),
    ("U-AI中級", "ユーエーアイちゅうきゅう"),
    ("U-AI", "ユーエーアイ"),
    ("Googleアカウント", "グーグルアカウント"),
    ("Googleドキュメント", "グーグルドキュメント"),
    ("Google Chrome", "グーグルクローム"),
    ("Google", "グーグル"),
    ("ChatGPT", "チャットジーピーティー"),
    ("NotebookLM", "ノートブックエルエム"),
    ("Anthropic", "アンソロピック"),
    ("Claude", "クロード"),
    ("Gemini", "ジェミニ"),
    ("Bing", "ビング"),
    ("Word", "ワード"),
    ("Excel", "エクセル"),
    ("PowerPoint", "パワーポイント"),
    ("LINE", "ライン"),
    ("Proプラン", "プロプラン"),
    ("Pro", "プロ"),
    ("あなたのdot", "あなたのドット"),
    ("dot", "ドット"),
    ("Day1〜3", "デイ1から3"),
    ("Day1", "デイ1"),
    ("Day2", "デイ2"),
    ("Day3", "デイ3"),
    ("A1", "エーワン"),
    ("A2", "エーツー"),
    ("A3用", "エースリーよう"),
    ("A3", "エースリー"),
    ("A4以降", "エーフォーいこう"),
    ("A4", "エーフォー"),
    ("B11", "ビーイレブン"),
    ("B1", "ビーワン"),
    ("B2", "ビーツー"),
    ("B3", "ビースリー"),
    ("B4", "ビーフォー"),
    ("B8", "ビーエイト"),
    ("B9", "ビーナイン"),
    ("07または08で", "セクション7または8で"),
    ("07で使った", "セクション7でつかった"),
    ("10で作り", "セクション10でつくり"),
    ("「…」", "「さんてんメニュー」"),
    ("500MB", "500メガバイト"),
    ("200MB", "200メガバイト"),
    ("申込URL", "もうしこみユーアールエル"),
    ("URL", "ユーアールエル"),
    ("PDF", "ピーディーエフ"),
    ("SNS", "エスエヌエス"),
    ("Webページ", "ウェブページ"),
    ("Web", "ウェブ"),
    ("FAQ", "エフエーキュー"),
    ("OK", "オッケー"),
    ("NG", "エヌジー"),
    ("AI", "エーアイ"),
    # Japanese polyphones / counters / tricky readings
    ("一手順一操作", "いちてじゅん、いちそうさ"),
    ("一問勝負", "いちもんしょうぶ"),
    ("一泊二日", "いっぱくふつか"),
    ("一週間分", "いっしゅうかんぶん"),
    ("一言ずつ", "ひとことずつ"),
    ("一言を", "ひとことを"),
    ("一言", "ひとこと"),
    ("一行ずつ", "いちぎょうずつ"),
    ("1〜2行", "1から2ぎょう"),
    ("一行", "いちぎょう"),
    ("三行", "さんぎょう"),
    ("3行", "さんぎょう"),
    ("二人組", "ふたりぐみ"),
    ("一人でも", "ひとりでも"),
    ("一人で", "ひとりで"),
    ("一人", "ひとり"),
    ("二人", "ふたり"),
    ("1人", "ひとり"),
    ("2人", "ふたり"),
    ("一つずつ", "ひとつずつ"),
    ("一つ", "ひとつ"),
    ("二つ", "ふたつ"),
    ("三つ", "みっつ"),
    ("四つ", "よっつ"),
    ("五つ", "いつつ"),
    ("1つ", "ひとつ"),
    ("2つ", "ふたつ"),
    ("3つ", "みっつ"),
    ("4つ", "よっつ"),
    ("5つ", "いつつ"),
    ("一歩先", "いっぽさき"),
    ("一歩", "いっぽ"),
    ("一から", "いちから"),
    ("2〜3個", "2から3こ"),
    ("2〜3日", "2から3にち"),
    ("1〜3個", "1から3こ"),
    ("3日間", "みっかかん"),
    ("各日の", "かくじつの"),
    ("午前10時", "ごぜんじゅうじ"),
    ("午後1時", "ごごいちじ"),
    ("午後2時", "ごごにじ"),
    ("午前", "ごぜん"),
    ("午後", "ごご"),
    ("15分", "じゅうごふん"),
    ("20分", "にじゅっぷん"),
    ("約5分", "やくごふん"),
    ("3分くらい", "さんぷんくらい"),
    ("3分", "さんぷん"),
    ("大さじ1", "おおさじ1"),
    ("大さじ", "おおさじ"),
    ("献立表", "こんだてひょう"),
    ("献立", "こんだて"),
    ("表形式", "ひょうけいしき"),
    ("表にして", "ひょうにして"),
    ("表にします", "ひょうにします"),
    ("表にまとめ", "ひょうにまとめ"),
    ("表・チェックリスト", "ひょうや、チェックリスト"),
    ("人向けに", "ひとむけに"),
    ("人向け", "ひとむけ"),
    ("ログインしている方は", "ログインしているかたは"),
    ("初めて使う方は", "はじめてつかうかたは"),
    ("アカウントがある方は", "アカウントがあるかたは"),
    ("分からない", "わからない"),
    ("分かる", "わかる"),
    ("分かり", "わかり"),
    ("言い方", "いいかた"),
    ("使い方", "つかいかた"),
    ("返し方", "かえしかた"),
    ("選び方", "えらびかた"),
    ("頼み方", "たのみかた"),
    ("見せ方", "みせかた"),
    ("送り方", "おくりかた"),
    ("答え方", "こたえかた"),
    ("書き方", "かきかた"),
    ("示し方", "しめしかた"),
    ("進め方", "すすめかた"),
    ("考え方", "かんがえかた"),
    ("やり方", "やりかた"),
    ("元のメモ", "もとのメモ"),
    ("元の情報", "もとのじょうほう"),
    ("元の資料", "もとのしりょう"),
    ("元のお知らせ", "もとのおしらせ"),
    ("元の文", "もとのぶん"),
    ("元の", "もとの"),
    ("元資料", "もとしりょう"),
    ("発信元", "はっしんもと"),
    ("手元", "てもと"),
    ("申込方法", "もうしこみほうほう"),
    ("申込内容", "もうしこみないよう"),
    ("申込先", "もうしこみさき"),
    ("申込の", "もうしこみの"),
    ("申込", "もうしこみ"),
    ("締切", "しめきり"),
    ("ボタン名", "ボタンめい"),
    ("講座名", "こうざめい"),
    ("モデル名", "モデルめい"),
    ("サービス名", "サービスめい"),
    ("アカウント名", "アカウントめい"),
    ("チャット名", "チャットめい"),
    ("プロジェクト名", "プロジェクトめい"),
    ("件名", "けんめい"),
    ("氏名", "しめい"),
    ("実名", "じつめい"),
    ("インターネット上から", "インターネットじょうから"),
    ("どちらが上という", "どちらがうえという"),
    ("画面右上", "がめんみぎうえ"),
    ("画面左下", "がめんひだりした"),
    ("画面上部", "がめんじょうぶ"),
    ("プロジェクト内にある", "プロジェクトないにある"),
    ("プロジェクト内に", "プロジェクトないに"),
    ("空欄", "くうらん"),
    ("有無", "うむ"),
    ("重複", "ちょうふく"),
    ("汎用", "はんよう"),
    ("必須", "ひっす"),
    ("代替", "だいたい"),
    ("施策", "しさく"),
    ("補足", "ほそく"),
    ("網羅", "もうら"),
    ("要旨", "ようし"),
    ("稟議", "りんぎ"),
    ("議事録", "ぎじろく"),
    ("雛形", "ひながた"),
    ("ひな形", "ひながた"),
    ("箇条書き", "かじょうがき"),
    ("走り書き", "はしりがき"),
    ("下書き", "したがき"),
    ("言葉づかい", "ことばづかい"),
    ("見比べ", "みくらべ"),
    ("見落とし", "みおとし"),
    ("見本", "みほん"),
    ("貼り付け", "はりつけ"),
    ("貼ります", "はります"),
    ("貼る", "はる"),
    ("役割", "やくわり"),
    ("役目", "やくめ"),
    ("役立つ", "やくだつ"),
    ("役立った", "やくだった"),
    ("固有名詞", "こゆうめいし"),
    ("自動更新", "じどうこうしん"),
    ("更新周期", "こうしんしゅうき"),
    ("更新日", "こうしんび"),
    ("解約方法", "かいやくほうほう"),
    ("私たち", "わたしたち"),
    ("私", "わたし"),
    ("何が", "なにが"),
    ("何を", "なにを"),
    ("何に", "なにに"),
    ("何から", "なにから"),
    ("何の", "なんの"),
    ("成果物", "せいかぶつ"),
    ("別の物", "べつのもの"),
    ("土曜日", "どようび"),
    ("日曜日", "にちようび"),
    ("掲示板", "けいじばん"),
    ("黒板", "こくばん"),
    ("①の", "いちばんの"),
    ("②の", "にばんの"),
    ("③の", "さんばんの"),
    ("④の", "よんばんの"),
    ("⑤の", "ごばんの"),
    ("⑥の", "ろくばんの"),
    ("⑦の", "ななばんの"),
    ("①", "いちばんの、"),
    ("②", "にばんの、"),
    ("③", "さんばんの、"),
    ("④", "よんばんの、"),
    ("⑤", "ごばんの、"),
    ("⑥", "ろくばんの、"),
    ("⑦", "ななばんの、"),
    ("Chatと", "チャットと"),
    ("Chatで", "チャットで"),
    ("Chatの", "チャットの"),
    ("Chatを", "チャットを"),
]


def find_fish_api_key() -> Optional[str]:
    """Env var first; macOS Keychain only when running on macOS. Never prints the key."""
    env_key = (
        os.environ.get("FISHAUDIO_API_KEY")
        or os.environ.get("FISH_AUDIO_API_KEY")
        or os.environ.get("FISH_API_KEY")
    )
    if env_key and len(env_key.strip()) > 20:
        return env_key.strip()
    if sys.platform != "darwin" or not shutil.which("security"):
        return None
    for cmd in (
        ["security", "find-generic-password", "-s", "FishAudio", "-w"],
        ["security", "find-generic-password", "-s", "FISHAUDIO_API_KEY", "-w"],
        ["security", "find-generic-password", "-s", "fish-audio-api-key", "-w"],
    ):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and len(res.stdout.strip()) > 20:
            return res.stdout.strip()
    return None


def get_fish_api_key() -> str:
    key = find_fish_api_key()
    if not key:
        raise RuntimeError(
            "FishAudio API key not found (set FISHAUDIO_API_KEY or macOS Keychain 'FishAudio')."
        )
    return key


# AI-cliché detector phrases (aligned with coji/natural-japanese lint rules)
AI_CLICHE_PHRASES: tuple[str, ...] = (
    "と言えるでしょう",
    "非常に重要",
    "さまざまなメリットが存在",
    "枚挙にいとまがありません",
    "一石を投じる",
    "パラダイムシフト",
    "単なる〜ではなく",
    "〜と言っても過言ではありません",
)


def lint_japanese_narration(text: str) -> list[str]:
    """Deterministically detect unnatural AI clichés in narration text."""
    return [phrase for phrase in AI_CLICHE_PHRASES if phrase in text]


import ctypes
import threading
from ctypes import util as _ctypes_util
from typing import Any

_CF_LOCK = threading.Lock()
_CF_LIB: Any = None
_CF_LATIN_HIRAGANA: Any = None
_KANJI_TOKEN_RE = re.compile(r"[\u4e00-\u9fff々ヶヵ]")


class _CFRange(ctypes.Structure):
    _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]


def _init_cf_tokenizer() -> bool:
    global _CF_LIB, _CF_LATIN_HIRAGANA
    if _CF_LIB is not None:
        return bool(_CF_LIB)
    if sys.platform != "darwin":
        _CF_LIB = False
        return False
    try:
        lib_path = _ctypes_util.find_library("CoreFoundation")
        if not lib_path:
            _CF_LIB = False
            return False
        cf = ctypes.cdll.LoadLibrary(lib_path)
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateMutableCopy.restype = ctypes.c_void_p
        cf.CFStringCreateMutableCopy.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        cf.CFStringTransform.restype = ctypes.c_bool
        cf.CFStringTransform.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFStringTokenizerCreate.restype = ctypes.c_void_p
        cf.CFStringTokenizerCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            _CFRange,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        cf.CFStringTokenizerAdvanceToNextToken.restype = ctypes.c_ulong
        cf.CFStringTokenizerAdvanceToNextToken.argtypes = [ctypes.c_void_p]
        cf.CFStringTokenizerCopyCurrentTokenAttribute.restype = ctypes.c_void_p
        cf.CFStringTokenizerCopyCurrentTokenAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        cf.CFStringTokenizerGetCurrentTokenRange.restype = _CFRange
        cf.CFStringTokenizerGetCurrentTokenRange.argtypes = [ctypes.c_void_p]
        cf.CFStringCreateWithSubstring.restype = ctypes.c_void_p
        cf.CFStringCreateWithSubstring.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _CFRange]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        _CF_LATIN_HIRAGANA = cf.CFStringCreateWithCString(None, b"Latin-Hiragana", 0x08000100)
        _CF_LIB = cf
        return True
    except Exception:
        _CF_LIB = False
        return False


def _cf_to_str(cf_str: Any) -> str:
    if not cf_str or not _CF_LIB:
        return ""
    buf = ctypes.create_string_buffer(8192)
    _CF_LIB.CFStringGetCString(cf_str, buf, 8192, 0x08000100)
    return buf.value.decode("utf-8", errors="ignore")


def parse_reading_dict_text(raw_text: str) -> dict[str, str]:
    """
    Parse custom Kanji -> Hiragana reading mappings from JSON, Markdown table, CSV/TSV, or `漢字=ひらがな` lines.
    """
    text = raw_text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                data = obj.get("readings", obj) if isinstance(obj.get("readings"), dict) else obj
                return {
                    str(k).strip(): str(v).strip()
                    for k, v in data.items()
                    if str(k).strip() and str(v).strip() and not str(k).startswith("_")
                }
        except Exception as exc:
            logger.debug("Failed to parse reading dict text as JSON: %s", exc)

    out: dict[str, str] = {}
    for line in text.splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#") or ln.startswith(">") or ln.startswith("<!--"):
            continue
        # Markdown table row: | 漢字 | ひらがな | ... |
        if ln.startswith("|") and ln.endswith("|"):
            cells = [c.strip().strip("`") for c in ln.strip("|").split("|")]
            if len(cells) >= 2:
                k, v = cells[0], cells[1]
                if (
                    k
                    and v
                    and k not in ("漢字・単語 (原文)", "漢字", "単語", "原文", "Word", "Surface")
                    and not set(k) <= {"-", ":", " "}
                ):
                    out[k] = v
            continue
        # Key=Value, Key\tValue, Key,Value, Key:Value
        for sep in ("\t", "=", "=>", "->", "→", ",", "："):
            if sep in ln:
                parts = ln.split(sep, 1)
                k, v = parts[0].strip().strip("`\"'"), parts[1].strip().strip("`\"'")
                if k and v:
                    out[k] = v
                break
    return out


def load_package_reading_dict(package_dir: Optional[Path] = None, reading_dict_arg: str = "") -> dict[str, str]:
    """
    Load package-level explicit `user_overrides` from `reading_dict.json` and optional `--reading-dict` override file.
    Does not load auto-extracted reference Kanji word lists as active replacements so standard Kanji preserve
    natural Japanese pitch accent (Prosody-Preserving TTS).
    """
    merged: dict[str, str] = {}
    if package_dir is not None:
        dict_json = package_dir / "reading_dict.json"
        if dict_json.exists() and dict_json.is_file():
            try:
                obj = json.loads(dict_json.read_text(encoding="utf-8"))
                if isinstance(obj, dict) and isinstance(obj.get("user_overrides"), dict):
                    for k, v in obj["user_overrides"].items():
                        if str(k).strip() and str(v).strip():
                            merged[str(k).strip()] = str(v).strip()
            except Exception as exc:
                logger.debug("Failed to load package reading_dict.json: %s", exc)
    if reading_dict_arg:
        p = Path(reading_dict_arg).resolve()
        if p.exists() and p.is_file():
            try:
                merged.update(parse_reading_dict_text(p.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.debug("Failed to load reading_dict_arg: %s", exc)
    return merged


def strip_brackets_for_tts(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"(^|[。！？、「『\s])(?:\[[^\]]*\]|［[^］]*］)(?:で使った|で作った|で学んだ|の|で|では|とは|から|へ|に|を|が|は)?\s*",
        r"\1",
        t,
    )
    t = re.sub(r"(?:\[[^\]]*\]|［[^］]*］)の", "", t)
    t = re.sub(r"\[[^\]]*\]|［[^］]*］", "", t)
    return t


def kanji_to_hiragana_sentence(
    text: str, custom_dict: Optional[dict[str, str]] = None
) -> tuple[str, dict[str, str]]:
    """
    Convert a Japanese sentence into a 100% Hiragana/Katakana reading base while preserving
    particles (は/へ/を), punctuation, and custom dictionary overrides.
    Also returns a word-level {kanji_word: hiragana_reading} map extracted from the sentence.
    """
    word_map: dict[str, str] = {}
    t = strip_brackets_for_tts(text)

    # 1. Unify built-in contextual dictionary + custom user dictionary (custom overrides same key),
    # and apply multi-character entries (len >= 2 or non-Kanji symbols) in strict descending length order
    # so shorter substrings (e.g. '使った', '後', '分') never clobber longer compounds ('07で使った', '午後2時', '分からない').
    unified: dict[str, str] = dict(S2_PRO_SAFE_REPLACEMENTS)
    if custom_dict:
        for k, v in custom_dict.items():
            if k and v:
                # Only allow 1-char Kanji if not a polysemous standalone Kanji, or handle 1-char Kanji at token level
                if len(k) >= 2 or not _KANJI_TOKEN_RE.search(k):
                    unified[k] = v

    for k, v in sorted(unified.items(), key=lambda x: len(x[0]), reverse=True):
        if k and (len(k) >= 2 or not _KANJI_TOKEN_RE.search(k)) and k in t:
            if _KANJI_TOKEN_RE.search(k) and len(k) >= 2 and k not in word_map:
                word_map[k] = v
            t = t.replace(k, v)

    t = t.replace("→", "、つぎに、")
    t = re.sub(r"・+", "、", t)
    t = re.sub(r"、{2,}", "、", t)
    t = re.sub(r"[ \t]+", " ", t).strip()

    # 2. Convert any remaining Kanji words via macOS CoreFoundation CFStringTokenizer
    with _CF_LOCK:
        if _init_cf_tokenizer() and _CF_LIB:
            s_ref = _CF_LIB.CFStringCreateWithCString(None, t.encode("utf-8"), 0x08000100)
            if s_ref:
                length = _CF_LIB.CFStringGetLength(s_ref)
                tok = _CF_LIB.CFStringTokenizerCreate(None, s_ref, _CFRange(0, length), 0, None)
                replacements: list[tuple[int, int, str, str]] = []
                if tok:
                    while _CF_LIB.CFStringTokenizerAdvanceToNextToken(tok):
                        r = _CF_LIB.CFStringTokenizerGetCurrentTokenRange(tok)
                        sub_ref = _CF_LIB.CFStringCreateWithSubstring(None, s_ref, r)
                        surface = _cf_to_str(sub_ref)
                        if sub_ref:
                            _CF_LIB.CFRelease(sub_ref)
                        if _KANJI_TOKEN_RE.search(surface):
                            if custom_dict and len(surface) >= 2 and surface in custom_dict:
                                hira = custom_dict[surface]
                                replacements.append((r.location, r.length, surface, hira))
                                word_map[surface] = hira
                                continue
                            latin = _CF_LIB.CFStringTokenizerCopyCurrentTokenAttribute(tok, 1 << 16)
                            if latin:
                                mut = _CF_LIB.CFStringCreateMutableCopy(None, 0, latin)
                                _CF_LIB.CFStringTransform(mut, None, _CF_LATIN_HIRAGANA, False)
                                hira = (
                                    _cf_to_str(mut)
                                    .replace("~tsu", "っ")
                                    .replace("~", "")
                                    .replace(" ", "")
                                )
                                if mut:
                                    _CF_LIB.CFRelease(mut)
                                _CF_LIB.CFRelease(latin)
                                if hira:
                                    replacements.append((r.location, r.length, surface, hira))
                                    if len(surface) >= 2 and surface not in word_map:
                                        word_map[surface] = hira
                    _CF_LIB.CFRelease(tok)
                _CF_LIB.CFRelease(s_ref)
                if replacements:
                    u16 = t.encode("utf-16-le")
                    for loc, ln, _surf, hira in reversed(replacements):
                        start_b = loc * 2
                        end_b = (loc + ln) * 2
                        u16 = u16[:start_b] + hira.encode("utf-16-le") + u16[end_b:]
                    t = u16.decode("utf-16-le", errors="ignore")

    return t.strip(), word_map


def normalize_for_s2_pro(
    text: str,
    custom_dict: Optional[dict[str, str]] = None,
    all_hiragana: bool = False,
    hiragana_instruction: Optional[str] = None,
) -> str:
    if all_hiragana:
        t = strip_brackets_for_tts(text)
        # If the input is already 100% Hiragana/Katakana (e.g. from `narration_tts` or `narration_kana`),
        # preserve the author's exact Hiragana phrasing and breath pauses while still applying any
        # explicit custom_dict overrides.
        if not _KANJI_TOKEN_RE.search(t):
            if custom_dict:
                for k, v in sorted(custom_dict.items(), key=lambda x: len(x[0]), reverse=True):
                    if k and v and k in t:
                        t = t.replace(k, v)
            t = t.replace("→", "、つぎに、")
            t = re.sub(r"・+", "、", t)
            t = re.sub(r"、{2,}", "、", t)
            return t.strip()
        hira_text, _ = kanji_to_hiragana_sentence(text, custom_dict=custom_dict)
        return hira_text
    # Default: Prosody-Preserving Hybrid Normalization via 16,563+ Built-in Dictionary + Hiragana Instruction Fallback for OOV
    try:
        from .tts_dictionary import normalize_prosody_Japanese_tts
    except ImportError:
        from tts_dictionary import normalize_prosody_Japanese_tts

    prosody_text, _ = normalize_prosody_Japanese_tts(
        text, custom_dict=custom_dict, hiragana_instruction=hiragana_instruction
    )
    return prosody_text


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


def verify_mp4(path: Path, expected_w: int = 1920, expected_h: int = 1080) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,color_space,sample_rate:stream_tags=language:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    info = json.loads(out)
    streams = info.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not (v_stream and a_stream):
        raise RuntimeError(
            f"Verification failed for {path}: video={bool(v_stream)}, audio={bool(a_stream)}"
        )
    if v_stream.get("width") != expected_w or v_stream.get("height") != expected_h:
        raise RuntimeError(
            f"Resolution mismatch for {path}: {v_stream.get('width')}x{v_stream.get('height')} (expected {expected_w}x{expected_h})"
        )
    return info


def resolve_tts_provider(requested: str) -> tuple[str, Optional[str]]:
    """Return (provider, fish_api_key). `auto`: fish -> edge -> say, with a loud warning."""
    requested = (requested or "auto").lower()
    fish_key = find_fish_api_key() if requested in ("auto", "fish") else None
    edge_ok = bool(shutil.which("edge-tts"))
    say_ok = sys.platform == "darwin" and bool(shutil.which("say"))
    if requested == "fish":
        if not fish_key:
            get_fish_api_key()  # raises with guidance
        return "fish", fish_key
    if requested == "edge":
        if not edge_ok:
            raise RuntimeError("edge-tts not found. Install: pip install edge-tts (github.com/rany2/edge-tts)")
        return "edge", None
    if requested == "say":
        if not say_ok:
            raise RuntimeError("macOS `say` is only available on macOS.")
        return "say", None
    if fish_key:
        return "fish", fish_key
    fallback = "edge" if edge_ok else ("say" if say_ok else "")
    if not fallback:
        raise RuntimeError(
            "No TTS available: set FISHAUDIO_API_KEY, or install edge-tts, or run on macOS (say)."
        )
    print(
        f"⚠️  [TTS FALLBACK] Fish Audio key not found -> using '{fallback}'. "
        "Voice will differ from the standard announcer voice (ca8c24e0...)."
    )
    return fallback, None


def _postprocess_tts(raw_path: Path, out_mp3: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
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


def synthesize_tts(
    text: str,
    out_mp3: Path,
    api_key: Optional[str],
    voice_id: str = DEFAULT_VOICE_ID,
    model: str = DEFAULT_MODEL,
    provider: str = "fish",
    custom_dict: Optional[dict[str, str]] = None,
    all_hiragana: bool = False,
    hiragana_instruction: Optional[str] = None,
) -> float:
    spoken_text = normalize_for_s2_pro(
        text,
        custom_dict=custom_dict,
        all_hiragana=all_hiragana,
        hiragana_instruction=hiragana_instruction,
    )
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
    if provider == "fish":
        sig_src = {"model": model, **payload_dict}  # unchanged -> v2 caches stay valid
    elif provider == "edge":
        sig_src = {"provider": "edge", "voice": EDGE_VOICE, "text": spoken_text}
    else:
        sig_src = {"provider": "say", "voice": SAY_VOICE, "text": spoken_text}
    sig = hashlib.sha256(
        json.dumps(sig_src, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    meta_file = out_mp3.with_suffix(f".{sig}.ok")

    if out_mp3.exists() and out_mp3.stat().st_size > 1000 and meta_file.exists():
        return ffprobe_duration(out_mp3)

    for old_ok in out_mp3.parent.glob(f"{out_mp3.stem}.*.ok"):
        old_ok.unlink(missing_ok=True)

    if provider == "fish":
        raw_path = out_mp3.with_suffix(f".{sig}.raw.mp3")
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
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    raw_path.write_bytes(resp.read())
                break
            except Exception as err:
                if attempt == 3:
                    raise RuntimeError(f"Fish Audio TTS failed after 4 attempts: {err}") from err
                time.sleep(2 * (attempt + 1))
    elif provider == "edge":
        raw_path = out_mp3.with_suffix(f".{sig}.raw.mp3")
        subprocess.run(
            ["edge-tts", "--voice", EDGE_VOICE, "--text", text.strip(), "--write-media", str(raw_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        raw_path = out_mp3.with_suffix(f".{sig}.raw.aiff")
        subprocess.run(
            ["say", "-v", SAY_VOICE, "-o", str(raw_path), text.strip()],
            check=True,
        )

    _postprocess_tts(raw_path, out_mp3)
    raw_path.unlink(missing_ok=True)
    meta_file.write_text(spoken_text, encoding="utf-8")
    return ffprobe_duration(out_mp3)


def pad_mp3_to(src: Path, seconds: float) -> Path:
    """Pad scene audio with trailing silence so audio == scene frames (prevents A/V drift)."""
    dst = src.with_name(f"{src.stem}.pad{int(round(seconds * 1000))}.mp3")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-af", f"apad=pad_dur=5.0,atrim=0:{seconds:.3f}",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(dst),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


def fit_or_pad_mp3_to(src: Path, target_seconds: float, actual_dur: float) -> Path:
    """Fit or pad scene audio to exact target_seconds (used with --reuse-silent-video)."""
    if actual_dur <= target_seconds + 0.015:
        return pad_mp3_to(src, target_seconds)
    tempo = min(1.30, max(1.0, actual_dur / max(target_seconds - 0.04, 0.2)))
    dst = src.with_name(f"{src.stem}.fit{int(round(target_seconds * 1000))}.mp3")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-af", f"atempo={tempo:.4f},apad=pad_dur=5.0,atrim=0:{target_seconds:.3f}",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(dst),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


def sync_package_assets(package_dir: Path, target_id: str, sub: str) -> None:
    """Copy <package>/<sub>/* (videos, etc.) into Remotion public/<target_id>/<sub>/."""
    src_dir = package_dir / sub
    if not src_dir.exists():
        return
    dst_dir = PUBLIC_DIR / target_id / sub
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in src_dir.iterdir():
        if f.is_file():
            target = dst_dir / f.name
            shutil.copy2(f, target)
            os.chmod(target, 0o644)
    if sys.platform == "darwin":
        subprocess.run(["xattr", "-cr", str(dst_dir)], check=False)


def sync_package_images(package_dir: Path, target_id: str) -> Path:
    src_images = package_dir / "images"
    dst_images = PUBLIC_DIR / target_id / "images"
    dst_images.mkdir(parents=True, exist_ok=True)
    if src_images.exists():
        for img in src_images.iterdir():
            if img.is_file():
                target = dst_images / img.name
                shutil.copy2(img, target)
                os.chmod(target, 0o644)
        if sys.platform == "darwin":
            subprocess.run(["xattr", "-cr", str(dst_images)], check=False)

    # Also sync to generic lesson01 for backwards compatibility
    legacy_dst = PUBLIC_DIR / "lesson01" / "images"
    legacy_dst.mkdir(parents=True, exist_ok=True)
    if src_images.exists():
        for img in src_images.iterdir():
            if img.is_file():
                shutil.copy2(img, legacy_dst / img.name)
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
            tip_text = ""
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
                scene_obj["table"] = {
                    "headers": md_info["headers"],
                    "rows": md_info["rows"],
                }
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
                scene_obj["steps"] = [
                    {"num": str(bi+1), "title": f"ポイント {bi+1}", "desc": b}
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
    try:
        try:
            from .compile_input_to_spec import derive_subvideo_jobs_from_full_scenes
            from .edit_storyboard import apply_hiragana_readings_to_spec, polish_spec_scenes
        except ImportError:
            from compile_input_to_spec import derive_subvideo_jobs_from_full_scenes
            from edit_storyboard import apply_hiragana_readings_to_spec, polish_spec_scenes

        for jid, jdata in list(compiled["jobs"].items()):
            polished, p_changes = polish_spec_scenes(jdata.get("scenes", []), mode="deterministic")
            jdata["scenes"] = polished
            if p_changes:
                print(f"  ✨ [auto-compile] {jid}: polished {len(p_changes)} scenes (removed repeats & smoothed Japanese flow)")
        if len(compiled["jobs"]) == 1:
            only_jid = next(iter(compiled["jobs"].keys()))
            only_scenes = compiled["jobs"][only_jid].get("scenes", [])
            if only_jid.endswith("-full") and len(only_scenes) >= 1:
                for sub_jid, sub_vtype, sub_scenes in derive_subvideo_jobs_from_full_scenes(lesson_id, only_scenes):
                    if sub_jid not in compiled["jobs"]:
                        compiled["jobs"][sub_jid] = {
                            "videoType": sub_vtype,
                            "lessonTitle": compiled["jobs"][only_jid].get("lessonTitle", lesson_title),
                            "scenes": sub_scenes,
                        }
        compiled, _, _ = apply_hiragana_readings_to_spec(compiled, load_package_reading_dict(package_dir))
    except Exception as e:
        print(f"  ⚠️  [auto-compile] Auto-polish / Hiragana dictionary pre-population warning: {e}")

    auto_out = package_dir / "scenes_spec.auto.json"
    auto_out.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    pkg_spec_out = package_dir / "scenes_spec.json"
    if not pkg_spec_out.exists():
        pkg_spec_out.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    return compiled


def _draw_blue_caption_bar_png(text: str, out_png: Path, width: int = 1920, height: int = 1080) -> None:
    """
    Render a transparent canvas with the dark-blue bottom SubtitleBar (`rgba(15, 23, 42, 240)`)
    at the bottom of the frame so imported videos get the exact same clean blue caption bar
    (and cover any old bottom subtitles in the original footage).
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = max(20, int(round(width * 0.015)))
    font = None
    for fp in (
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ):
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception as exc:
                logger.debug("Failed to load font %s: %s", fp, exc)
    if font is None:
        font = ImageFont.load_default()

    clean_txt = re.sub(r"\[[^\]]*\]|［[^］]*］", "", text).strip()
    if not clean_txt:
        img.save(out_png)
        return

    # Wrap text if wider than 82% of canvas width
    max_line_chars = max(18, int((width * 0.80) / max(font_size, 1)))
    lines: list[str] = []
    cur = ""
    for ch in clean_txt:
        cur += ch
        if len(cur) >= max_line_chars and ch in "、。！？ ":
            lines.append(cur.strip())
            cur = ""
        elif len(cur) >= max_line_chars + 6:
            lines.append(cur.strip())
            cur = ""
    if cur.strip():
        lines.append(cur.strip())
    lines = lines[:3]

    pad_x = int(round(width * 0.022))
    pad_y = int(round(height * 0.015))
    line_h = int(round(font_size * 1.42))
    total_text_h = line_h * len(lines)

    line_widths = []
    for ln in lines:
        try:
            bbox = draw.textbbox((0, 0), ln, font=font)
            line_widths.append(bbox[2] - bbox[0])
        except Exception:
            line_widths.append(len(ln) * font_size)
    box_w = min(int(width * 0.90), max(max(line_widths, default=200) + pad_x * 2, int(width * 0.42)))
    box_h = total_text_h + pad_y * 2

    box_x0 = (width - box_w) // 2
    box_y1 = height - int(round(height * 0.024))
    box_y0 = box_y1 - box_h

    draw.rounded_rectangle(
        [(box_x0, box_y0), (box_x0 + box_w, box_y1)],
        radius=16,
        fill=(15, 23, 42, 240),
        outline=(255, 255, 255, 45),
        width=2,
    )

    y_cursor = box_y0 + pad_y
    for ln, lw in zip(lines, line_widths):
        tx = (width - lw) // 2
        draw.text((tx, y_cursor), ln, font=font, fill=(255, 255, 255, 255))
        y_cursor += line_h

    img.save(out_png)


def render_direct_video_clips_silent_mp4(
    built_scenes: list[dict],
    silent_mp4: Path,
    canvas_w: int,
    canvas_h: int,
    work_dir: Path,
) -> None:
    """
    Fast direct FFmpeg + Pillow renderer for imported videos (`source_type == 'video'`).
    Preserves full-screen original video clips (`videos/scene_XXX.mp4`), syncs duration to each
    scene's new Hiragana TTS audio, and burns in the clean dark-blue bottom SubtitleBar.
    """
    seg_dir = work_dir / "_direct_clip_segs"
    seg_dir.mkdir(parents=True, exist_ok=True)
    seg_files: list[Path] = []

    for idx, sc in enumerate(built_scenes):
        target_dur = max(1.0, sc["frames"] / FPS)
        vid_rel = sc.get("video", "")
        clip_src = PUBLIC_DIR / vid_rel if vid_rel else None
        img_rel = sc.get("image", "")
        img_src = PUBLIC_DIR / img_rel if img_rel else None

        narr = strip_brackets_for_tts(sc.get("narration", "")).strip()
        sents = [s.strip() for s in re.split(r"(?<=[。！？!?])\s*", narr) if s.strip()] or [narr]
        total_chars = max(1, sum(len(s) for s in sents))

        ov_pngs: list[tuple[Path, float, float]] = []
        accum = 0
        for si, s in enumerate(sents):
            st_t = (accum / total_chars) * target_dur
            accum += len(s)
            et_t = (accum / total_chars) * target_dur if si < len(sents) - 1 else target_dur + 0.5
            png_p = seg_dir / f"sub_{idx:03d}_{si:02d}.png"
            _draw_blue_caption_bar_png(s, png_p, width=canvas_w, height=canvas_h)
            ov_pngs.append((png_p, st_t, et_t))

        seg_out = seg_dir / f"seg_{idx:03d}.mp4"
        if clip_src and clip_src.exists():
            clip_dur = max(0.2, ffprobe_duration(clip_src))
            pts_factor = target_dur / clip_dur
            # Smoothly time-stretch if within [0.55, 1.65]; otherwise hold final frame
            if 0.55 <= pts_factor <= 1.65:
                base_vf = (
                    f"[0:v]setpts={pts_factor:.4f}*PTS,"
                    f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                    f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=#0f172a,"
                    f"fps={FPS},tpad=stop_mode=clone:stop_duration=3.0,trim=duration={target_dur:.3f},setpts=PTS-STARTPTS[v0]"
                )
            else:
                base_vf = (
                    f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                    f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=#0f172a,"
                    f"fps={FPS},tpad=stop_mode=clone:stop_duration={max(3.0, target_dur):.3f},trim=duration={target_dur:.3f},setpts=PTS-STARTPTS[v0]"
                )
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(clip_src)]
        elif img_src and img_src.exists():
            base_vf = (
                f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=#0f172a,"
                f"fps={FPS},trim=duration={target_dur:.3f},setpts=PTS-STARTPTS[v0]"
            )
            cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{target_dur:.3f}", "-i", str(img_src)]
        else:
            raise FileNotFoundError(f"Neither video clip nor image found for scene {sc.get('id')}")

        fc_parts = [base_vf]
        last_lbl = "v0"
        for oi, (png_p, st_t, et_t) in enumerate(ov_pngs):
            cmd.extend(["-i", str(png_p)])
            in_idx = oi + 1
            next_lbl = f"v{oi + 1}"
            fc_parts.append(
                f"[{last_lbl}][{in_idx}:v]overlay=0:0:enable='between(t,{st_t:.3f},{et_t:.3f})'[{next_lbl}]"
            )
            last_lbl = next_lbl

        cmd.extend(
            [
                "-filter_complex",
                ";".join(fc_parts),
                "-map",
                f"[{last_lbl}]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "19",
                "-pix_fmt",
                "yuv420p",
                str(seg_out),
            ]
        )
        subprocess.run(cmd, check=True)
        seg_files.append(seg_out)

    concat_txt = seg_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in seg_files) + "\n", encoding="utf-8")
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
            str(concat_txt),
            "-c",
            "copy",
            str(silent_mp4),
        ],
        check=True,
    )


def resolve_scenes_spec(package_dir: Path, scenes_json_arg: str, course_id: str, lesson_id: str, batch_job_ids: list[str]) -> dict:
    """
    3-Stage Deterministic Resolution:
    1. Explicit `--scenes-json` path if provided
    2. Pre-curated golden spec in `<skill_root>/examples/<course_id>_<lesson_id>_scenes_spec.json`
       (or `<lesson_id>_scenes_spec.json` for backwards compatibility with a01)
    3. Zero-LLM deterministic compiler from `video-job.json` + `video-script.md`
    """
    if scenes_json_arg:
        p = Path(scenes_json_arg).resolve()
        if p.exists():
            print(f"[Spec] Using explicit scenes spec: {p}")
            return json.loads(p.read_text(encoding="utf-8"))

    # Check if package_dir contains a pre-curated scenes_spec.json
    pkg_spec_path = package_dir / "scenes_spec.json"
    if pkg_spec_path.exists():
        spec = json.loads(pkg_spec_path.read_text(encoding="utf-8"))
        jobs_map = spec.get("jobs", spec)
        if all(jid in jobs_map for jid in batch_job_ids):
            print(f"[Spec] Using package scenes spec: {pkg_spec_path}")
            return spec

    # Check course-specific golden spec next
    golden_path = SKILL_ROOT / "examples" / f"{course_id}_{lesson_id}_scenes_spec.json"
    if not golden_path.exists() and course_id == "ai-user-a01":
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
    parser.add_argument("--package-dir", default="", help="Path to lesson package (contains batch.json)")
    parser.add_argument(
        "--input",
        default="",
        help="Any document to auto-package: .md/.txt/.pdf/.pptx/.docx/.html or http(s) URL",
    )
    parser.add_argument("--title", default="", help="Video title override when using --input")
    parser.add_argument("--scenes-json", default="", help="Optional path to scenes_spec.json (auto-resolved if omitted)")
    parser.add_argument("--downloads-dir", default=DEFAULT_DOWNLOADS_DIR, help="Copy/ZIP destination ('' to disable)")
    parser.add_argument("--zip-name", default="", help="Optional zip filename in Downloads dir")
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help="Fish Audio reference_id")
    parser.add_argument("--tts", default="auto", choices=["auto", "fish", "edge", "say"], help="TTS provider")
    parser.add_argument("--tts-workers", type=int, default=4, help="Parallel TTS workers")
    parser.add_argument("--aspect", default="16:9", choices=list(ASPECT_PRESETS), help="Canvas aspect ratio")
    parser.add_argument("--theme", default="corporate-blue", choices=list(THEME_CHOICES), help="Brand colour theme")
    parser.add_argument("--output-suffix", default="", help="Optional suffix for output filenames (e.g. '_下位モデル')")
    parser.add_argument("--job", default="", help="Optional jobId filter to render only a specific job")
    parser.add_argument(
        "--only-scene",
        default="",
        help="Fast single-scene preview: render only this scene ID or 1-based index into _scene_previews/",
    )
    parser.add_argument(
        "--auto-polish",
        dest="auto_polish",
        action="store_true",
        default=True,
        help="Automatically run deterministic Japanese de-duplication & context transition polishing before TTS synthesis (default: enabled)",
    )
    parser.add_argument(
        "--no-auto-polish",
        dest="auto_polish",
        action="store_false",
        help="Disable automatic Japanese de-duplication & context transition polishing",
    )
    parser.add_argument(
        "--embed-soft-subs",
        action="store_true",
        help="Also embed an MP4 mov_text soft subtitle stream (off by default to prevent double captions over the burned-in blue SubtitleBar)",
    )
    parser.add_argument(
        "--reuse-silent-video",
        action="store_true",
        help="Reuse existing Remotion .silent.mp4 & frame counts when only TTS pronunciation or audio mastering changed",
    )
    parser.add_argument(
        "--reading-dict",
        default="",
        help="Path to custom Kanji->Hiragana reading file (.json, .md table, .csv, .tsv, or key=value lines)",
    )
    parser.add_argument(
        "--all-hiragana",
        action="store_true",
        help="Convert all Kanji in TTS narration into Hiragana base before synthesis (off by default to preserve natural Kanji pitch accent / intonation)",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Pre-render voice & intonation check: synthesize only TTS MP3 audio files and generate interactive audio_preview.html without running Remotion video rendering",
    )
    parser.add_argument(
        "--bgm",
        default="corporate-ambient",
        choices=["none", "corporate-ambient", "warm-acoustic", "upbeat-tech", "lofi-study"],
        help="Royalty-free background music bed with automatic sidechain ducking under speech (default: corporate-ambient; pass 'none' to disable)",
    )
    parser.add_argument(
        "--bgm-volume",
        type=float,
        default=0.16,
        help="Base volume for --bgm before sidechain ducking (default: 0.16)",
    )
    parser.add_argument(
        "--se",
        action="store_true",
        default=True,
        help="Enable subtle chapter/section transition chime sound effects (enabled by default)",
    )
    parser.add_argument(
        "--no-se",
        dest="se",
        action="store_false",
        help="Disable subtle chapter/section transition chime sound effects",
    )
    parser.add_argument(
        "--guest-voice-id",
        default="ja-JP-KeitaNeural",
        help="Secondary voice ID for guest turns in multi-speaker `dialogue` scenes",
    )
    args = parser.parse_args()

    if not args.package_dir and not args.input:
        parser.error("either --package-dir or --input is required")
    if not (REMOTION_ROOT / "node_modules" / "@remotion" / "cli").exists():
        raise RuntimeError(
            f"Remotion not installed at {REMOTION_ROOT}. Run `cd remotion && npm install` "
            "or set COURSE_VIDEO_REMOTION_ROOT."
        )

    if args.input:
        try:
            from .compile_input_to_spec import build_package
        except ImportError:
            from compile_input_to_spec import build_package

        pkg_out = Path(args.package_dir).resolve() if args.package_dir else None
        package_dir = build_package(args.input, out_dir=pkg_out, title=args.title or None)
        print(f"[0/4] Compiled input -> package: {package_dir}")
    else:
        package_dir = Path(args.package_dir).resolve()
    canvas_w, canvas_h = ASPECT_PRESETS[args.aspect]
    batch_file = package_dir / "batch.json"
    if not batch_file.exists():
        raise FileNotFoundError(f"batch.json not found in {package_dir}")

    batch_data = json.loads(batch_file.read_text(encoding="utf-8"))
    course_id = batch_data.get("courseId") or batch_data.get("course_id", "ai-user-a01")
    lesson_id = batch_data.get("lessonId") or batch_data.get("lesson_id", package_dir.name)
    jobs = batch_data.get("jobs", [])
    batch_job_ids = [j.get("jobId") or j.get("id") for j in jobs]

    scenes_spec = resolve_scenes_spec(package_dir, args.scenes_json, course_id, lesson_id, batch_job_ids)
    jobs_map = scenes_spec.get("jobs", scenes_spec)

    # Always ensure 3-video standard (`<lesson>-full` ダイジェスト + `操作実演` + `活用事例`) when only 1 `-full` job is present
    derived_new_jobs = False
    if len(jobs_map) == 1:
        only_jid = next(iter(jobs_map.keys()))
        only_scenes = jobs_map[only_jid].get("scenes", [])
        if only_jid.endswith("-full") and len(only_scenes) >= 1 and batch_data.get("source_type") != "video":
            try:
                from .compile_input_to_spec import derive_subvideo_jobs_from_full_scenes
            except ImportError:
                from compile_input_to_spec import derive_subvideo_jobs_from_full_scenes
            for sub_jid, sub_vtype, sub_scenes in derive_subvideo_jobs_from_full_scenes(lesson_id, only_scenes):
                if sub_jid not in jobs_map:
                    jobs_map[sub_jid] = {
                        "videoType": sub_vtype,
                        "lessonTitle": jobs_map[only_jid].get("lessonTitle", ""),
                        "scenes": sub_scenes,
                    }
                    derived_new_jobs = True

    # Ensure all jobs present in scenes_spec (`jobs_map`) are also included in `jobs` list
    batch_updated = False
    for spec_jid, spec_jdata in jobs_map.items():
        if spec_jid not in batch_job_ids and isinstance(spec_jdata, dict) and "scenes" in spec_jdata:
            jobs.append(
                {
                    "id": spec_jid,
                    "folder": spec_jid,
                    "output": f"{spec_jid}/{spec_jid}.mp4",
                    "video_type": spec_jdata.get("videoType", "解説"),
                }
            )
            batch_job_ids.append(spec_jid)
            batch_updated = True

    if batch_updated:
        batch_data["jobs"] = jobs
        batch_data["job_count"] = len(jobs)
        batch_file.write_text(json.dumps(batch_data, ensure_ascii=False, indent=2), encoding="utf-8")
    if derived_new_jobs and (package_dir / "scenes_spec.json").exists():
        (package_dir / "scenes_spec.json").write_text(
            json.dumps(scenes_spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for jid in batch_job_ids:
        if jid not in jobs_map:
            raise ValueError(f"Job '{jid}' from batch.json is missing in resolved scenes spec")

    target_id = f"{course_id}_{lesson_id}"
    print(f"[1/4] Syncing images for {target_id} with chmod 644 & xattr -cr...")
    sync_package_images(package_dir, target_id)
    sync_package_assets(package_dir, target_id, "videos")

    provider, api_key = resolve_tts_provider(args.tts)
    custom_reading_dict = load_package_reading_dict(package_dir, args.reading_dict)
    if custom_reading_dict:
        print(f"[Readings] Loaded {len(custom_reading_dict)} custom Kanji->Hiragana readings for {target_id}")
    work_dir = REMOTION_ROOT / target_id / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    SCENES_OUT_DIR.mkdir(parents=True, exist_ok=True)

    rendered_mp4s: list[Path] = []

    for job in jobs:
        job_id = job.get("jobId") or job.get("id")
        if args.job and job_id != args.job:
            continue
        rel_output = job.get("output") or f"{job.get('folder', job_id)}/{job_id}.mp4"
        job_spec = jobs_map[job_id]
        scenes = list(job_spec["scenes"])
        if args.auto_polish:
            try:
                from .edit_storyboard import polish_spec_scenes, save_spec_with_backup
            except ImportError:
                from edit_storyboard import polish_spec_scenes, save_spec_with_backup

            scenes, polish_changes = polish_spec_scenes(scenes, mode="deterministic")
            if polish_changes:
                print(f"  ✨ [auto-polish] {job_id}: polished {len(polish_changes)} scenes for natural Japanese & context")
                job_spec["scenes"] = scenes
                pkg_spec_file = package_dir / "scenes_spec.json"
                if pkg_spec_file.exists():
                    save_spec_with_backup(pkg_spec_file, scenes_spec)
        if args.only_scene:
            filtered = [
                sc
                for i, sc in enumerate(scenes)
                if sc.get("id") == args.only_scene or str(i + 1) == str(args.only_scene)
            ]
            if not filtered:
                raise ValueError(f"--only-scene '{args.only_scene}' not found in job '{job_id}'")
            scenes = filtered
        video_type = job_spec.get("videoType") or job.get("video_type") or job.get("type", "full")
        lesson_title = (
            job_spec.get("lessonTitle")
            or batch_data.get("lessonTitle")
            or batch_data.get("lesson_title", "")
        )

        print(
            f"\n[2/4] Synthesizing TTS provider={provider} (voice={args.voice_id[:8] if provider == 'fish' else (EDGE_VOICE if provider == 'edge' else SAY_VOICE)}, workers={args.tts_workers}) for {job_id} ({len(scenes)} scenes)..."
        )
        for sc in scenes:
            hits = lint_japanese_narration(sc.get("narration", ""))
            if hits:
                print(f"  ⚠️  [natural-japanese] {sc.get('id')}: AI-cliché phrases {hits} (source kept verbatim)")
        job_audio_dir = work_dir / job_id
        job_audio_dir.mkdir(parents=True, exist_ok=True)

        # Parallel TTS synthesis for 3-4x speedup
        pkg_audio_dir = package_dir / "_audio_preview" / job_id
        pkg_audio_dir.mkdir(parents=True, exist_ok=True)

        try:
            from .universal_video_upgrades import (
                auto_enrich_visual_scenes,
                compute_scene_subtitle_cues,
                mix_bgm_and_se_with_ducking,
                synthesize_dialogue_scene,
            )
        except ImportError:
            from universal_video_upgrades import (
                auto_enrich_visual_scenes,
                compute_scene_subtitle_cues,
                mix_bgm_and_se_with_ducking,
                synthesize_dialogue_scene,
            )

        def _synth_one(item: tuple[int, dict]) -> tuple[int, Path, float, list[dict], list[dict]]:
            idx, sc = item
            sc_id = sc["id"]
            mp3_path = job_audio_dir / f"{idx:02d}_{sc_id}.mp3"
            if sc.get("dialogue") and isinstance(sc.get("dialogue"), list):
                dur, d_turns, d_cues = synthesize_dialogue_scene(
                    sc,
                    mp3_path,
                    synthesize_tts,
                    api_key,
                    default_voice_id=args.voice_id,
                    guest_voice_id=args.guest_voice_id,
                    provider=provider,
                    custom_dict=custom_reading_dict,
                    all_hiragana=args.all_hiragana,
                )
                shutil.copy2(mp3_path, pkg_audio_dir / f"{idx:02d}_{sc_id}.mp3")
                return idx, mp3_path, dur, d_turns, d_cues

            hira_inst = (
                sc.get("narration_tts")
                or sc.get("narration_kana")
                or sc.get("reading")
                or ""
            )
            if args.all_hiragana:
                tts_base_text = hira_inst or sc.get("narration", "")
            else:
                # Default Prosody-Preserving Mode: prioritize 16,563+ Built-in Dictionary + custom_dict,
                # and fall back to Hiragana text instruction (`narration_tts` / `narration_kana`) for OOV words!
                tts_base_text = sc.get("narration_prosody") or sc.get("narration", "")
            scene_voice = str(sc.get("voiceId") or args.voice_id)
            dur = synthesize_tts(
                tts_base_text,
                mp3_path,
                api_key,
                voice_id=scene_voice,
                provider=provider,
                custom_dict=custom_reading_dict,
                all_hiragana=args.all_hiragana,
                hiragana_instruction=hira_inst,
            )
            shutil.copy2(mp3_path, pkg_audio_dir / f"{idx:02d}_{sc_id}.mp3")
            return idx, mp3_path, dur, [], []

        with ThreadPoolExecutor(max_workers=max(1, args.tts_workers)) as pool:
            synth_results = list(pool.map(_synth_one, list(enumerate(scenes))))

        synth_results.sort(key=lambda x: x[0])

        mp3_list: list[Path] = []
        cursor_frame = 0
        built_scenes = []

        out_tag = f"{job_id}_{scenes[0]['id']}" if args.only_scene else job_id
        silent_mp4 = work_dir / f"{out_tag}.silent.mp4"
        build_json_path = SCENES_OUT_DIR / f"{out_tag}.build.json"
        is_direct_video = bool(
            (batch_data.get("source_type") == "video" or scenes_spec.get("source_type") == "video")
            and all(s.get("kind") == "video-clip" for s in scenes)
        )
        reuse_silent = bool(
            args.reuse_silent_video
            and not is_direct_video
            and not args.only_scene
            and silent_mp4.exists()
            and build_json_path.exists()
        )
        existing_frames_map: dict[str, int] = {}
        if reuse_silent:
            try:
                old_build = json.loads(build_json_path.read_text(encoding="utf-8"))
                existing_frames_map = {
                    s["id"]: int(s["frames"]) for s in old_build.get("scenes", []) if "id" in s and "frames" in s
                }
            except Exception:
                reuse_silent = False

        for idx, mp3_path, dur, d_turns, d_cues in synth_results:
            sc = scenes[idx]
            sc_id = sc["id"]
            if reuse_silent and sc_id in existing_frames_map:
                frames = existing_frames_map[sc_id]
            else:
                frames = max(90, int(math.ceil(dur * FPS)))
            sc_copy = auto_enrich_visual_scenes(dict(sc))
            if d_turns:
                sc_copy["dialogue"] = d_turns
            for img_key in ("image", "secondImage", "video"):
                if sc_copy.get(img_key):
                    clean_img = sc_copy[img_key].replace("../", "").lstrip("./")
                    if not clean_img.startswith(f"{target_id}/"):
                        sc_copy[img_key] = f"{target_id}/{clean_img}"
            if sc_copy.get("kind") == "video-clip" and sc_copy.get("video"):
                clip_file = PUBLIC_DIR / sc_copy["video"]
                if not clip_file.exists():
                    raise FileNotFoundError(f"video-clip source not found: {clip_file}")
                clip_dur = ffprobe_duration(clip_file)
                # Speed up long clips up to 2x to fit the narration; extend the scene
                # (with padded silence) if the clip is still longer.
                rate = min(2.0, max(1.0, clip_dur / max(dur, 0.1)))
                clip_frames = int(math.ceil(clip_dur / rate * FPS))
                if not reuse_silent and not is_direct_video:
                    frames = max(frames, clip_frames)
                sc_copy["videoPlaybackRate"] = round(rate, 3)
                sc_copy["videoFrames"] = clip_frames
            # Compute acoustic pause-aligned subtitle cues (`subtitleCues`) before padding
            if d_cues:
                sc_copy["subtitleCues"] = d_cues
            elif not sc_copy.get("subtitleCues"):
                sc_copy["subtitleCues"] = compute_scene_subtitle_cues(
                    mp3_path,
                    sc_copy.get("narration", ""),
                    scene_frames=frames,
                    audio_dur_sec=dur,
                    fps=FPS,
                )
            if reuse_silent and sc_id in existing_frames_map:
                mp3_path = fit_or_pad_mp3_to(mp3_path, frames / FPS, dur)
            elif frames / FPS > dur + 0.02:
                mp3_path = pad_mp3_to(mp3_path, frames / FPS)
            sc_copy["frames"] = frames
            sc_copy["startFrame"] = cursor_frame
            built_scenes.append(sc_copy)
            cursor_frame += frames
            mp3_list.append(mp3_path)
            print(f"  - [{idx+1:02d}/{len(scenes):02d}] {sc_id}: {dur:.2f}s ({frames}f)")

        combined_mp3 = PUBLIC_DIR / target_id / f"{out_tag}.mp3"
        combined_mp3.parent.mkdir(parents=True, exist_ok=True)
        concat_mp3_files(mp3_list, combined_mp3)
        shutil.copy2(combined_mp3, pkg_audio_dir / f"{out_tag}_full.mp3")

        # Persist enriched scene metadata (`subtitleCues`, `spotlights`, `frames`, `startFrame`) back to scenes_spec.json
        if not args.only_scene:
            job_spec["scenes"] = built_scenes
            pkg_spec_path = package_dir / "scenes_spec.json"
            if pkg_spec_path.exists():
                pkg_spec_path.write_text(
                    json.dumps(scenes_spec, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        if args.audio_only:
            print(f"  ✓ [Audio-Only] Synthesized {len(scenes)} scene MP3s ({cursor_frame / FPS:.1f}s) -> {pkg_audio_dir}")
            continue

        build_payload = {
            "id": out_tag,
            "courseId": course_id,
            "lessonId": lesson_id,
            "videoType": video_type,
            "lessonTitle": lesson_title,
            "fps": FPS,
            "width": canvas_w,
            "height": canvas_h,
            "theme": args.theme,
            "totalFrames": cursor_frame,
            "scenes": built_scenes,
        }

        build_json_path.write_text(
            json.dumps(build_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        props_json_path = work_dir / f"{out_tag}.props.json"
        props_json_path.write_text(
            json.dumps({"id": out_tag, "build": build_payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if args.only_scene:
            final_pkg_mp4 = package_dir / "_scene_previews" / f"{out_tag}.mp4"
        else:
            final_pkg_mp4 = package_dir / rel_output
        final_pkg_mp4.parent.mkdir(parents=True, exist_ok=True)

        remotion_cli = REMOTION_ROOT / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if is_direct_video:
            print(f"[3/4] Direct Video Clip + Blue Caption Bar Remastering for {job_id} ({cursor_frame} frames)...")
            render_direct_video_clips_silent_mp4(built_scenes, silent_mp4, canvas_w, canvas_h, work_dir)
        elif reuse_silent:
            print(f"[3/4] Reusing existing Remotion silent video for {job_id} ({cursor_frame} frames)...")
        else:
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
                    "--concurrency=4",
                    "--timeout=120000",
                    "--color-space=bt709",  # limited-range yuv420p BT.709 (iOS/QuickTime safe)
                ],
                cwd=str(REMOTION_ROOT),
                check=True,
            )

        print(f"[4/4] Mastering video (BT.709 + EBU R128 -14.5 LUFS 48kHz + burned-in blue SubtitleBar) -> {final_pkg_mp4}...")
        srt_path = work_dir / f"{job_id}.srt"
        srt_entries = []
        srt_idx = 1
        for sc in built_scenes:
            start_sec = sc["startFrame"] / FPS
            dur_sec = sc["frames"] / FPS
            narr = sc.get("narration", "").strip()
            if not narr:
                continue
            sents = [s.strip() for s in re.split(r"(?<=[。！？\n])", narr) if s.strip()]
            total_chars = max(1, sum(len(s) for s in sents))
            cur_sec = start_sec
            for s in sents:
                s_dur = dur_sec * (len(s) / total_chars)
                ms_s = int(round(cur_sec * 1000))
                ms_e = int(round((cur_sec + s_dur) * 1000))
                t_s = f"{ms_s//3600000:02d}:{(ms_s%3600000)//60000:02d}:{(ms_s%60000)//1000:02d},{ms_s%1000:03d}"
                t_e = f"{ms_e//3600000:02d}:{(ms_e%3600000)//60000:02d}:{(ms_e%60000)//1000:02d},{ms_e%1000:03d}"
                srt_entries.append(f"{srt_idx}\n{t_s} --> {t_e}\n{s}\n")
                cur_sec += s_dur
                srt_idx += 1
        srt_path.write_text("\n".join(srt_entries), encoding="utf-8")

        ffmpeg_bin = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
        if not Path(ffmpeg_bin).exists():
            ffmpeg_bin = "ffmpeg"

        # Optional BGM (with sidechain auto-ducking) + Chapter Transition SE mixing
        master_audio_mp3 = combined_mp3
        if args.bgm != "none" or args.se:
            print(f"  🎵 [Audio Mix] Mixing BGM ({args.bgm}) + SE ({args.se}) with sidechain auto-ducking...")
            mixed_mp3 = work_dir / f"{out_tag}.mixed.mp3"
            master_audio_mp3 = mix_bgm_and_se_with_ducking(
                combined_mp3,
                built_scenes,
                total_dur_sec=cursor_frame / FPS,
                out_mp3=mixed_mp3,
                bgm_style=args.bgm,
                enable_se=args.se,
                bgm_volume=args.bgm_volume,
                ffmpeg_bin=ffmpeg_bin,
            )

        p1 = subprocess.run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-i",
                str(master_audio_mp3),
                "-af",
                "loudnorm=I=-14.5:TP=-1.5:LRA=11:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        m_match = re.search(r"\{[\s\S]*?\"input_i\"[\s\S]*?\}", p1.stderr)
        if m_match:
            ln_stats = json.loads(m_match.group(0))
            af_filter = (
                f"loudnorm=I=-14.5:TP=-1.5:LRA=11:"
                f"measured_I={ln_stats['input_i']}:measured_TP={ln_stats['input_tp']}:"
                f"measured_LRA={ln_stats['input_lra']}:measured_thresh={ln_stats['input_thresh']}:"
                f"offset={ln_stats['target_offset']}:linear=true"
            )
        else:
            af_filter = "loudnorm=I=-14.5:TP=-1.5:LRA=11"

        mux_cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-i",
            str(silent_mp4),
            "-i",
            str(master_audio_mp3),
        ]
        if srt_entries and args.embed_soft_subs:
            mux_cmd.extend(["-i", str(srt_path), "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0"])
        else:
            mux_cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])

        mux_cmd.extend(
            [
                "-c:v",
                "copy",
                "-bsf:v",
                "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-colorspace",
                "bt709",
                "-af",
                af_filter,
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-b:a",
                "192k",
            ]
        )
        if srt_entries and args.embed_soft_subs:
            mux_cmd.extend(
                [
                    "-c:s",
                    "mov_text",
                    "-metadata:s:s:0",
                    "language=jpn",
                    "-metadata:s:s:0",
                    "title=Japanese",
                ]
            )
        mux_cmd.extend(["-shortest", "-movflags", "+faststart", str(final_pkg_mp4)])
        subprocess.run(
            mux_cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        verify_mp4(final_pkg_mp4, canvas_w, canvas_h)
        rendered_mp4s.append(final_pkg_mp4)

        if args.downloads_dir:
            dl_dir = Path(args.downloads_dir)
            out_stem = f"{job_id}{args.output_suffix}"
            course_videos_dir = dl_dir / f"{course_id}_videos"
            course_videos_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final_pkg_mp4, course_videos_dir / f"{out_stem}.mp4")

            dl_mp4 = dl_dir / f"{course_id}_{out_stem}.mp4"
            shutil.copy2(final_pkg_mp4, dl_mp4)

            if args.output_suffix:
                suffixed_dir = dl_dir / f"{course_id}_videos{args.output_suffix}"
                suffixed_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(final_pkg_mp4, suffixed_dir / f"{out_stem}.mp4")

            for sub_dir_name in (
                f"{course_id}_videos",
                f"{lesson_id}_videos",
                f"{lesson_id}_2_videos",
                f"{lesson_id}_videos 2",
            ):
                candidate_dir = dl_dir / sub_dir_name
                if candidate_dir.exists() and candidate_dir.is_dir():
                    shutil.copy2(final_pkg_mp4, candidate_dir / f"{out_stem}.mp4")
            print(f"  ✓ Verified & synced to {dl_mp4} and {course_videos_dir}")

    if args.audio_only:
        try:
            from .edit_storyboard import export_audio_check_report
        except ImportError:
            from edit_storyboard import export_audio_check_report

        html_path, md_path = export_audio_check_report(package_dir, downloads_dir=args.downloads_dir)
        print(f"\n✓ [Audio-Only Pre-Check Complete] Voice & Intonation Studio HTML: {html_path}")
        print(f"✓ Voice & Intonation Markdown Sheet: {md_path}")
        return

    zip_name = args.zip_name or f"{course_id}_videos{args.output_suffix}.zip"
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
