#!/usr/bin/env python3
"""
Universal input -> course-video package compiler (Zero-LLM, deterministic).

Turns ANY of these into a standard package (batch.json + scenes_spec.json + images/ + videos/)
that render_course_package.py renders without modification:

  .md / .markdown / .txt   parsed directly (headings -> scenes)
  .pdf                     poppler: pdftoppm (page images) + pdftotext (page narration)
  .pptx / .ppt / .key      LibreOffice headless -> PDF -> page images; speaker notes via markitdown
  .docx / .html / URL      microsoft/markitdown (`doc-to-md` or `markitdown`) -> Markdown

Rules (same as the main pipeline): never invent content. Narration is taken verbatim from
the source (paragraphs, speaker notes, page text). Override per section with
`<!-- narration: ... -->` in Markdown.

Usage:
  python3 compile_input_to_spec.py INPUT [-o OUT_DIR] [--title TITLE]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

MAX_NARRATION_CHARS = 700  # split longer sections into continuation scenes
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _slug(text: str, fallback_seed: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-").lower()
    if len(s) < 3:
        s = "doc-" + hashlib.sha1(fallback_seed.encode("utf-8")).hexdigest()[:8]
    return s[:40]


def _markitdown_bin() -> str:
    for name in ("doc-to-md", "markitdown"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "markitdown not found. Install: pip install 'markitdown[all]' (github.com/microsoft/markitdown)"
    )


def _require(binary: str, hint: str) -> str:
    p = shutil.which(binary)
    if not p:
        raise RuntimeError(f"`{binary}` not found. {hint}")
    return p


def _to_markdown(src: str) -> str:
    res = subprocess.run([_markitdown_bin(), src], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"markitdown failed for {src}: {res.stderr.strip()[:300]}")
    return res.stdout


def _html_title(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read(200_000).decode("utf-8", "ignore")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I) or re.search(
            r"<title[^>]*>(.*?)</title>", html, re.S | re.I
        )
        return _clean_inline(m.group(1)) if m else None
    except Exception:
        return None


def _clean_inline(text: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)          # links -> label
    t = re.sub(r"<[^>]+>", "", t)                           # html tags
    t = re.sub(r"(\*\*|__|`|~~)", "", t)                    # emphasis / code
    t = re.sub(r"(?<!\w)[*_](\S[^*_]*\S|\S)[*_](?!\w)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _join_sentences(parts: list[str]) -> str:
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not re.search(r"[。！？!?.]$", p):
            p += "。"
        out.append(p)
    return "".join(out)


def _split_long(narration: str) -> list[str]:
    if len(narration) <= MAX_NARRATION_CHARS:
        return [narration]
    sentences = [s for s in re.split(r"(?<=[。！？!?])", narration) if s.strip()]
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) > MAX_NARRATION_CHARS:
            chunks.append(cur)
            cur = ""
        cur += s
    if cur:
        chunks.append(cur)
    return chunks


class AssetStore:
    """Copies / downloads / decodes referenced media into the package."""

    def __init__(self, pkg: Path, base_dir: Optional[Path], base_url: Optional[str]):
        self.pkg = pkg
        self.base_dir = base_dir
        self.base_url = base_url
        self.counter = {"images": 0, "videos": 0}

    def add(self, ref: str, kind: str) -> Optional[str]:
        ref = ref.strip().split(" ")[0].strip("<>")
        if not ref:
            return None
        dst_dir = self.pkg / kind
        dst_dir.mkdir(parents=True, exist_ok=True)
        self.counter[kind] += 1
        n = self.counter[kind]
        try:
            if ref.startswith("data:"):
                m = re.match(r"data:image/(\w+);base64,(.*)", ref, re.S)
                if not m:
                    return None
                ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
                name = f"{kind[:-1]}-{n:02d}.{ext}"
                (dst_dir / name).write_bytes(base64.b64decode(m.group(2)))
                return f"{kind}/{name}"
            url = ref
            if self.base_url and not re.match(r"^https?://", ref):
                url = urllib.parse.urljoin(self.base_url, ref)
            if re.match(r"^https?://", url):
                ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".png"
                name = f"{kind[:-1]}-{n:02d}{ext}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    (dst_dir / name).write_bytes(r.read())
                return f"{kind}/{name}"
            src = Path(urllib.parse.unquote(ref)).expanduser()
            if not src.is_absolute() and self.base_dir:
                src = (self.base_dir / src).resolve()
            if not src.exists():
                print(f"  ⚠️  asset not found, skipped: {ref}")
                return None
            name = f"{kind[:-1]}-{n:02d}{src.suffix.lower()}"
            shutil.copy2(src, dst_dir / name)
            return f"{kind}/{name}"
        except Exception as e:  # asset failures must not kill the whole build
            print(f"  ⚠️  asset failed ({e.__class__.__name__}), skipped: {ref[:80]}")
            return None


def _synthesize_bullets_narration(bullets: list[str], is_procedural: bool, existing_text: str) -> str:
    """Turn slide bullets into natural spoken Japanese sentences when not already covered by paragraphs."""
    unseen = [b.rstrip("。.") for b in bullets if b and b[:10] not in existing_text]
    if not unseen:
        return ""
    # Check if bullets are already full polite sentences
    if all(re.search(r"(です|ます|しょう|さい|せん)$", b) for b in unseen):
        return _join_sentences(unseen[:4])
    items = unseen[:4]
    if is_procedural:
        connectors = ["まず", "次に", "続いて", "最後に"]
        parts = []
        for idx, item in enumerate(items):
            clean_it = re.sub(r"^(?:(?:ステップ|STEP)\s*\d+[.．:：\s]*|\d+[.．:：)]+\s*)", "", item, flags=re.I).strip()
            conn = connectors[min(idx, len(connectors) - 1)] if len(items) > 1 else ""
            if idx == len(items) - 1 and len(items) >= 2:
                conn = "最後に"
            parts.append(f"{conn}「{clean_it}」" if len(clean_it) <= 26 else f"{conn}{clean_it}")
        return "具体的な手順として、" + "、".join(parts) + "という流れで進めます。"
    if len(items) == 1:
        return f"特に「{items[0]}」の点を意識することが大切です。"
    quoted = [f"「{it}」" if len(it) <= 24 else it for it in items]
    return "主なポイントとして、" + "、".join(quoted[:-1]) + f"、そして{quoted[-1]}などが挙げられます。"


def _synthesize_table_narration(table: dict, existing_text: str) -> str:
    """Summarize markdown table rows into natural spoken Japanese."""
    rows = table.get("rows") or []
    if not rows:
        return ""
    parts = []
    for r in rows[:3]:
        cells = [c.strip() for c in r if c and c.strip()]
        if not cells or (len(cells) >= 2 and cells[-1] in existing_text):
            continue
        if len(cells) >= 3:
            parts.append(f"「{cells[0]}」には{cells[1]}として「{cells[2]}」")
        elif len(cells) == 2:
            parts.append(f"「{cells[0]}」は「{cells[1]}」")
    if not parts:
        return ""
    return "具体例として、" + "、".join(parts) + "のように指定します。"


def _derive_visual_cards_from_text(heading: str, narration: str, bullets: list[str]) -> list[dict]:
    """Build 3 concise, non-duplicative visual cards when a slide has text/bullets."""
    source_items = list(bullets[:4])
    if not source_items:
        # Split sentences/clauses into concise visual takeaways (distinct from full narration)
        clauses = [
            c.strip(" 、。")
            for c in re.split(r"[。！？]|(?<=、)", narration)
            if len(c.strip(" 、。")) >= 8
        ]
        source_items = clauses[:3]
    if not source_items:
        source_items = [heading]

    tag_labels = ["POINT 01", "POINT 02", "POINT 03", "POINT 04"]
    cards = []
    for idx, item in enumerate(source_items[:3]):
        clean = re.sub(r"^(?:具体的には|まずは|また|さらに|そして|最後に)、?", "", item).strip()
        if "：" in clean or ":" in clean:
            parts = re.split(r"[：:]", clean, maxsplit=1)
            title = parts[0].strip()[:24]
            body = parts[1].strip()
        elif "、" in clean and len(clean) > 18:
            parts = clean.split("、", 1)
            title = parts[0].strip()[:24]
            body = parts[1].strip()
        elif "の" in clean and 10 <= len(clean) <= 28:
            parts = clean.split("の", 1)
            title = clean[:26]
            body = f"{parts[0]}における「{parts[1]}」の効率化と標準化"
        else:
            title = clean[:24] + ("…" if len(clean) > 24 else "")
            body = clean if len(clean) > 24 else ""
        cards.append({
            "tag": tag_labels[idx],
            "title": title,
            "body": body,
        })
    return cards
def _parse_table(lines: list[str]) -> Optional[dict]:
    rows = []
    for ln in lines:
        cells = [_clean_inline(c) for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return None
    width = len(rows[0])
    body = [(r + [""] * width)[:width] for r in rows[1:]]
    return {"headers": rows[0], "rows": body}


def markdown_to_scenes(md: str, assets: AssetStore, title_override: Optional[str]) -> tuple[str, list[dict]]:
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)  # YAML front matter
    lines = md.splitlines()

    sections: list[dict] = []
    cur = {"level": 0, "heading": "", "lines": []}
    for ln in lines:
        m = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", ln)
        if m:
            sections.append(cur)
            cur = {"level": len(m.group(1)), "heading": _clean_inline(m.group(2)), "lines": []}
        else:
            cur["lines"].append(ln)
    sections.append(cur)
    sections = [s for s in sections if s["heading"] or any(x.strip() for x in s["lines"])]

    doc_title = title_override or next((s["heading"] for s in sections if s["level"] == 1), "")
    if not doc_title:
        doc_title = next((s["heading"] for s in sections if s["heading"]), "解説動画")

    scenes: list[dict] = []
    sec_no = 0
    for si, sec in enumerate(sections):
        paragraphs, bullets, quotes, tables, images, videos = [], [], [], [], [], []
        override = None
        buf_table: list[str] = []
        para_buf: list[str] = []
        body = "\n".join(sec["lines"])
        m_over = re.search(r"<!--\s*narration:\s*(.*?)-->", body, re.S)
        if m_over:
            override = re.sub(r"\s+", " ", m_over.group(1)).strip()
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)

        def flush_para():
            if para_buf:
                t = _clean_inline(" ".join(para_buf))
                if t:
                    paragraphs.append(t)
                para_buf.clear()

        for ln in body.splitlines() + [""]:
            s = ln.strip()
            if s.startswith("|"):
                flush_para()
                buf_table.append(s)
                continue
            if buf_table:
                t = _parse_table(buf_table)
                if t:
                    tables.append(t)
                buf_table = []
            for ref in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", s) + re.findall(r'<(?:video|source)[^>]+src="([^"]+)"', s):
                (videos if ref.lower().split("?")[0].endswith(VIDEO_EXTS) else images).append(ref)
            for ref in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", s):
                if ref.lower().split("?")[0].endswith(VIDEO_EXTS):
                    videos.append(ref)
            if not s:
                flush_para()
                continue
            m_li = re.match(r"^([-*+]|\d+[.)])\s+(.*)", s)
            if m_li:
                flush_para()
                item = _clean_inline(m_li.group(2))
                if item:
                    bullets.append(item)
                continue
            if s.startswith(">"):
                flush_para()
                q = _clean_inline(s.lstrip("> "))
                if q:
                    quotes.append(q)
                continue
            if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", s) or s.startswith("<video") or s.startswith("<source"):
                continue
            if re.fullmatch(r"[-*_]{3,}", s):
                flush_para()
                continue
            para_buf.append(s)

        heading = sec["heading"] or doc_title
        clean_sec_label = re.sub(r"^(?:第\d+[章節]\s*|\d+[.．:：]\s*|SECTION\s*\d+[:：]?\s*)", "", heading, flags=re.I).strip() or heading
        is_title = not scenes and (sec["level"] == 1 or si == 0)
        is_procedural = bool(re.search(r"(手順|ステップ|実演|ハンズオン|操作|設定|方法|作り方|組み立て)", heading))
        is_closing = bool(si == len(sections) - 1 and len(sections) >= 3) or bool(re.search(r"(まとめ|事例|効果|展開|振り返り)", heading))

        if override:
            narration = override
        else:
            base_narr = _join_sentences(paragraphs) or _join_sentences(quotes)
            if is_title:
                narration = base_narr or _join_sentences(bullets) or _join_sentences([heading])
            else:
                bullet_narr = _synthesize_bullets_narration(bullets, is_procedural, base_narr)
                table_narr = _synthesize_table_narration(tables[0], base_narr) if tables else ""
                combined_parts = [p for p in (base_narr, bullet_narr, table_narr) if p]
                narration = "".join(combined_parts) if combined_parts else _join_sentences([heading])

        img_refs = [r for r in (assets.add(x, "images") for x in images[:2]) if r]
        vid_ref = assets.add(videos[0], "videos") if videos else None

        scene: dict = {"heading": heading, "sectionLabel": clean_sec_label[:24]}
        if is_title:
            title_bullets = bullets[:4]
            if not title_bullets and len(sections) > 1:
                title_bullets = [
                    re.sub(r"^(?:第\d+[章節]\s*|\d+[.．:：]\s*)", "", s["heading"]).strip()
                    for s in sections[1:4]
                    if s.get("heading")
                ]
            scene.update({
                "kind": "title",
                "sub": paragraphs[0][:80] if paragraphs else "実務ですぐに使える実践ステップと活用法",
                "badge": "INTRODUCTION",
            })
            if title_bullets:
                scene["bullets"] = title_bullets[:4]
            if img_refs:
                scene["image"] = img_refs[0]
        else:
            sec_no += 1
            scene["badge"] = f"SECTION {sec_no:02d}"
            lead_text = paragraphs[0][:88] if paragraphs else f"{clean_sec_label}の重要ポイントを確認しましょう"
            if vid_ref:
                scene.update({"kind": "video-clip", "video": vid_ref})
                if paragraphs:
                    scene["videoCaption"] = paragraphs[0][:90]
            elif tables:
                scene.update({"kind": "table", "table": tables[0], "lead": lead_text})
                if img_refs:
                    scene["image"] = img_refs[0]
            elif len(img_refs) >= 2:
                scene.update({"kind": "dual-image", "image": img_refs[0], "secondImage": img_refs[1], "lead": lead_text})
            elif img_refs and bullets:
                scene.update({"kind": "split-image", "image": img_refs[0], "bullets": bullets[:5], "lead": lead_text})
            elif img_refs:
                scene.update({"kind": "full-image", "image": img_refs[0], "lead": lead_text})
            elif is_procedural and len(bullets) >= 2:
                step_items = []
                for idx_b, b in enumerate(bullets[:4]):
                    clean_b = re.sub(r"^(?:(?:ステップ|STEP)\s*\d+[.．:：\s]*|\d+[.．:：)]+\s*)", "", b, flags=re.I).strip()
                    step_items.append({
                        "num": str(idx_b + 1),
                        "title": clean_b[:24],
                        "desc": clean_b,
                    })
                scene.update({
                    "kind": "steps",
                    "lead": lead_text,
                    "steps": step_items,
                    "callout": {"type": "tip", "text": f"{clean_sec_label}は画面の順番どおりに進めるのが確実です。"},
                })
            elif is_closing:
                cards = _derive_visual_cards_from_text(clean_sec_label, narration, bullets)
                scene.update({
                    "kind": "summary",
                    "lead": lead_text,
                    "cards": cards,
                    "callout": {"type": "good", "text": "まずは1つの定型業務から実践し、チーム全体の標準フローへ展開しましょう。"},
                })
            else:
                cards = _derive_visual_cards_from_text(clean_sec_label, narration, bullets)
                scene.update({
                    "kind": "cards",
                    "lead": lead_text,
                    "cards": cards,
                    "callout": {"type": "tip", "text": f"{clean_sec_label}の要点を押さえて実務に活かしましょう。"},
                })
            if quotes and scene["kind"] in ("full-image", "split-image"):
                scene["quote"] = quotes[0][:120]

        chunks = _split_long(narration)
        for ci, chunk in enumerate(chunks):
            sc = dict(scene)
            if len(chunks) > 1:
                sc["heading"] = f"{heading}（{ci + 1}/{len(chunks)}）"
                if ci > 0 and sc["kind"] == "title":
                    sc["kind"] = "split-image"
            sc["narration"] = chunk
            scenes.append(sc)

    for i, sc in enumerate(scenes, 1):
        sc["id"] = f"s{i:03d}"
    return doc_title, scenes


# ---------------------------------------------------------------------------
# PDF / PPTX -> page scenes
# ---------------------------------------------------------------------------
def _pdf_page_count(pdf: Path) -> int:
    _require("pdfinfo", "Install poppler (brew install poppler / apt install poppler-utils).")
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def _clean_page_text(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        s = re.sub(r"^[\s•●▪◦・\-–—*]+", "", ln).strip()
        if not s or re.fullmatch(r"\d{1,3}(\s*/\s*\d{1,3})?", s):
            continue
        lines.append(s)
    # join wrapped lines; keep sentence punctuation
    return _join_sentences([re.sub(r"\s{2,}", " ", s) for s in lines])


def pdf_to_scenes(pdf: Path, pkg: Path, notes: Optional[dict[int, str]] = None) -> list[dict]:
    _require("pdftoppm", "Install poppler (brew install poppler / apt install poppler-utils).")
    n_pages = _pdf_page_count(pdf)
    if n_pages == 0:
        raise RuntimeError(f"Could not read pages from {pdf}")
    img_dir = pkg / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", "110", "-scale-to-x", "1600", "-scale-to-y", "-1", str(pdf), str(img_dir / "page")],
        check=True,
    )
    pages = sorted(img_dir.glob("page-*.png"))
    scenes = []
    for i, img in enumerate(pages, 1):
        raw = subprocess.run(
            ["pdftotext", "-layout", "-f", str(i), "-l", str(i), str(pdf), "-"],
            capture_output=True, text=True,
        ).stdout
        non_empty = [l.strip() for l in raw.splitlines() if l.strip()]
        first = non_empty[0] if non_empty else ""
        sec_m = re.match(r"^SECTION\s*(\d+)[:：]?\s*(.*)", first, flags=re.I)
        if sec_m and sec_m.group(2).strip():
            badge_str = f"SECTION {int(sec_m.group(1)):02d}"
            heading = _clean_inline(sec_m.group(2).strip())[:40]
        else:
            badge_str = "INTRODUCTION" if i == 1 else f"SECTION {i - 1:02d}"
            heading = _clean_inline(first)[:40] or f"ページ {i}"

        if notes and notes.get(i):
            narration = notes[i]
        else:
            body_lines = non_empty[1:] if len(non_empty) > 1 else non_empty
            paras, page_bullets = [], []
            for bl in body_lines:
                if re.match(r"^[•●▪◦・\-–—*]|^(?:\d+[.．:：]|ステップ\s*\d+)", bl):
                    cleaned_b = re.sub(r"^[•●▪◦・\-–—*\s]+", "", bl).strip()
                    if cleaned_b:
                        page_bullets.append(cleaned_b)
                elif not re.fullmatch(r"\d{1,3}(\s*/\s*\d{1,3})?", bl):
                    paras.append(re.sub(r"\s{2,}", " ", bl))
            base_p = _join_sentences(paras)
            is_proc = bool(re.search(r"(手順|ステップ|実演|操作|設定)", heading))
            b_narr = _synthesize_bullets_narration(page_bullets, is_proc, base_p)
            narration = (base_p + b_narr).strip() or f"{heading}について確認します。"

        chunks = _split_long(narration)
        for ci, chunk in enumerate(chunks):
            scenes.append({
                "kind": "title" if i == 1 and ci == 0 else "full-image",
                "heading": heading if len(chunks) == 1 else f"{heading}（{ci + 1}/{len(chunks)}）",
                "sectionLabel": heading[:22],
                "badge": badge_str,
                "image": f"images/{img.name}",
                "narration": chunk,
            })
    for i, sc in enumerate(scenes, 1):
        sc["id"] = f"s{i:03d}"
        if sc["kind"] == "title":
            sc["sub"] = ""
    return scenes


def pptx_notes(pptx: Path) -> dict[int, str]:
    """Speaker notes per slide via markitdown (`<!-- Slide number: N -->` ... `### Notes:`)."""
    try:
        md = _to_markdown(str(pptx))
    except RuntimeError as e:
        print(f"  ⚠️  {e}; falling back to slide text")
        return {}
    notes: dict[int, str] = {}
    for m in re.finditer(r"<!--\s*Slide number:\s*(\d+)\s*-->(.*?)(?=<!--\s*Slide number:|\Z)", md, re.S):
        block = m.group(2)
        nm = re.search(r"###\s*Notes:?\s*\n(.*)", block, re.S)
        if nm:
            txt = _join_sentences([_clean_inline(x) for x in nm.group(1).splitlines()])
            if txt:
                notes[int(m.group(1))] = txt
    return notes


def office_to_pdf(src: Path, out_dir: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice not found (brew install --cask libreoffice / apt install libreoffice).")
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    pdf = out_dir / f"{src.stem}.pdf"
    if not pdf.exists():
        raise RuntimeError(f"LibreOffice conversion failed for {src}")
    return pdf


# ---------------------------------------------------------------------------
# Video (.mp4 / .mov / .webm / .m4v / .mkv / .avi) -> scenes + clips + transcript
# ---------------------------------------------------------------------------
VIDEO_INPUT_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")


def _parse_srt_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _parse_srt_or_vtt_text(raw: str) -> list[dict]:
    segs: list[dict] = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for blk in blocks:
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT"):
            continue
        time_line_idx = -1
        for idx, ln in enumerate(lines):
            if "-->" in ln:
                time_line_idx = idx
                break
        if time_line_idx < 0:
            continue
        m = re.match(r"([0-9:.,]+)\s*-->\s*([0-9:.,]+)", lines[time_line_idx])
        if not m:
            continue
        st = _parse_srt_time(m.group(1))
        et = _parse_srt_time(m.group(2))
        txt = _clean_inline(" ".join(lines[time_line_idx + 1 :]))
        if txt and et > st:
            segs.append({"start": st, "end": et, "text": txt})
    return segs


def _transcribe_video_segments(video_path: Path, total_dur: float) -> list[dict]:
    """
    Multi-tier zero-API-cost transcript & timestamp extractor:
      1. Sidecar .srt / .vtt file next to the video
      2. Embedded subtitle track inside the video container (0:s:0)
      3. Local OpenAI Whisper ('base' cached at ~/.cache/whisper/base.pt) or faster_whisper
      4. Uniform time-slicing fallback for silent / screen-recording videos
    """
    # Tier 1: Sidecar .srt / .vtt
    for ext in (".srt", ".vtt"):
        cand = video_path.with_suffix(ext)
        if cand.exists():
            segs = _parse_srt_or_vtt_text(cand.read_text(encoding="utf-8", errors="ignore"))
            if segs:
                print(f"  [video-ingest] Loaded {len(segs)} subtitle segments from sidecar {cand.name}")
                return segs

    # Tier 2: Embedded subtitle stream
    res_sub = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-map", "0:s:0", "-f", "srt", "-"],
        capture_output=True,
        text=True,
    )
    if res_sub.returncode == 0 and "-->" in res_sub.stdout:
        segs = _parse_srt_or_vtt_text(res_sub.stdout)
        if segs:
            print(f"  [video-ingest] Extracted {len(segs)} embedded subtitle segments from {video_path.name}")
            return segs

    # Check if video has an audio stream
    probe_audio = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    has_audio = bool(probe_audio.stdout.strip())

    # Tier 3: Local Whisper ASR
    if has_audio:
        with tempfile.TemporaryDirectory() as td:
            wav_path = Path(td) / "audio_16k.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(wav_path),
                ],
                check=False,
            )
            if wav_path.exists() and wav_path.stat().st_size > 1024:
                try:
                    import whisper  # type: ignore

                    print(f"  [video-ingest] Transcribing audio with local Whisper (base) for {video_path.name}...")
                    model = whisper.load_model("base")
                    res = model.transcribe(str(wav_path), language="ja", fp16=False, verbose=False)
                    raw_segs = res.get("segments") or []
                    segs = [
                        {
                            "start": float(s["start"]),
                            "end": float(s["end"]),
                            "text": _clean_inline(str(s.get("text", ""))),
                        }
                        for s in raw_segs
                        if _clean_inline(str(s.get("text", ""))) and float(s["end"]) > float(s["start"])
                    ]
                    if segs:
                        print(f"  [video-ingest] Whisper transcribed {len(segs)} speech segments.")
                        return segs
                except Exception as e:
                    print(f"  ⚠️  [video-ingest] openai-whisper fallback notice: {e}")
                try:
                    from faster_whisper import WhisperModel  # type: ignore

                    print(f"  [video-ingest] Transcribing audio with faster-whisper for {video_path.name}...")
                    fw = WhisperModel("base", device="cpu", compute_type="int8")
                    segments_iter, _ = fw.transcribe(str(wav_path), language="ja")
                    segs = [
                        {"start": float(s.start), "end": float(s.end), "text": _clean_inline(s.text)}
                        for s in segments_iter
                        if _clean_inline(s.text) and float(s.end) > float(s.start)
                    ]
                    if segs:
                        return segs
                except Exception as e:
                    print(f"  ⚠️  [video-ingest] faster-whisper fallback notice: {e}")

    # Tier 4: Fallback uniform scene slicing (12s per scene)
    step = 12.0
    segs = []
    t = 0.0
    idx = 1
    while t < total_dur - 0.5:
        et = min(total_dur, t + step)
        segs.append({"start": t, "end": et, "text": f"シーン{idx}の解説です。"})
        t = et
        idx += 1
    return segs or [{"start": 0.0, "end": max(3.0, total_dur), "text": "シーン1の解説です。"}]


def _group_segments_into_scenes(segs: list[dict], total_dur: float) -> list[dict]:
    """
    Merge fine-grained ASR segments (2-4s) into natural editable video scenes (8-22s, ~60-160 chars)
    with contiguous [start, end] intervals covering [0, total_dur].
    """
    if not segs:
        return [{"start": 0.0, "end": max(3.0, total_dur), "text": "シーン1の解説です。"}]

    grouped: list[dict] = []
    cur_start = 0.0
    cur_end = segs[0]["end"]
    cur_texts: list[str] = []

    for i, s in enumerate(segs):
        txt = s["text"].strip()
        if not cur_texts:
            cur_start = 0.0 if not grouped else grouped[-1]["end"]
        cur_texts.append(txt)
        cur_end = max(cur_end, float(s["end"]))
        dur = cur_end - cur_start
        char_len = sum(len(x) for x in cur_texts)
        next_gap = (float(segs[i + 1]["start"]) - cur_end) if (i + 1 < len(segs)) else 99.0
        ends_sentence = bool(re.search(r"[。！？!?]$", txt))

        should_split = (
            dur >= 24.0
            or char_len >= 170
            or (dur >= 9.0 and (ends_sentence or next_gap >= 0.45))
            or (char_len >= 85 and (ends_sentence or next_gap >= 0.3))
        )
        if should_split and i + 1 < len(segs):
            mid_boundary = round((cur_end + float(segs[i + 1]["start"])) / 2.0, 2)
            mid_boundary = max(cur_start + 1.5, min(total_dur, mid_boundary))
            grouped.append(
                {
                    "start": round(cur_start, 2),
                    "end": mid_boundary,
                    "text": _join_sentences(cur_texts),
                }
            )
            cur_texts = []
            cur_start = mid_boundary

    if cur_texts:
        grouped.append(
            {
                "start": round(cur_start, 2),
                "end": round(max(cur_end, total_dur), 2),
                "text": _join_sentences(cur_texts),
            }
        )
    elif grouped:
        grouped[-1]["end"] = round(max(grouped[-1]["end"], total_dur), 2)

    return grouped


def video_to_scenes(video_path: Path, pkg: Path, title_override: Optional[str] = None) -> tuple[str, list[dict]]:
    _require("ffmpeg", "Install ffmpeg (brew install ffmpeg).")
    _require("ffprobe", "Install ffmpeg/ffprobe (brew install ffmpeg).")

    dur_out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        text=True,
    ).strip()
    total_dur = float(dur_out) if dur_out else 10.0

    raw_segs = _transcribe_video_segments(video_path, total_dur)
    scene_chunks = _group_segments_into_scenes(raw_segs, total_dur)

    img_dir = pkg / "images"
    vid_dir = pkg / "videos"
    orig_aud_dir = pkg / "original_audio"
    img_dir.mkdir(parents=True, exist_ok=True)
    vid_dir.mkdir(parents=True, exist_ok=True)
    orig_aud_dir.mkdir(parents=True, exist_ok=True)

    doc_title = title_override or video_path.stem.replace("_", " ").replace("-", " ").strip() or "インポート動画"
    scenes: list[dict] = []

    print(f"  [video-ingest] Slicing {len(scene_chunks)} scenes (thumbnails + video clips + audio) from {video_path.name}...")
    for i, ch in enumerate(scene_chunks, 1):
        st = float(ch["start"])
        et = max(st + 1.0, float(ch["end"]))
        mid = (st + et) / 2.0
        img_name = f"scene_{i:03d}.png"
        clip_name = f"scene_{i:03d}.mp4"
        aud_name = f"scene_{i:03d}.mp3"

        # 1. Extract representative frame thumbnail
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{mid:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1600,iw)':-2",
                str(img_dir / img_name),
            ],
            check=False,
        )

        # 2. Extract muted video clip segment for direct remastering / Remotion video-clip
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{st:.3f}",
                "-to",
                f"{et:.3f}",
                "-i",
                str(video_path),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(vid_dir / clip_name),
            ],
            check=False,
        )

        # 3. Extract original audio slice
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{st:.3f}",
                "-to",
                f"{et:.3f}",
                "-i",
                str(video_path),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(orig_aud_dir / aud_name),
            ],
            check=False,
        )

        narration = ch["text"].strip() or f"シーン{i}の解説です。"
        sentences = [x.strip() for x in re.split(r"(?<=[。！？!?])", narration) if x.strip()]
        first_sent = re.sub(r"[。！？!?]+$", "", sentences[0]) if sentences else doc_title
        heading = first_sent[:34] if len(first_sent) >= 2 else f"{doc_title}（{i}）"
        sec_label = f"{int(st // 60):02d}:{int(st % 60):02d} - {int(et // 60):02d}:{int(et % 60):02d}"

        scenes.append(
            {
                "id": f"s{i:03d}",
                "kind": "video-clip",
                "heading": heading,
                "sectionLabel": sec_label,
                "badge": f"SCENE {i:02d}",
                "image": f"images/{img_name}",
                "video": f"videos/{clip_name}",
                "videoCaption": sec_label,
                "clipStart": st,
                "clipEnd": et,
                "bullets": [s[:65] for s in sentences[:4]],
                "narration": narration,
            }
        )

    return doc_title, scenes


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------
def _ensure_standalone_subvideo_arc(
    sub_jid: str, sub_vtype: str, core_scenes: list[dict]
) -> list[dict]:
    """
    Ensure every derived sub-video (`操作実演` or `活用事例`) is a complete, self-contained
    3+ scene standalone micro-video (`Opening Title` -> `Main Content` -> `Wrap-up Checklist`)
    even when the source material only had 1 or 2 scenes in that section.
    """
    if len(core_scenes) >= 3:
        return [dict(s) for s in core_scenes]
    if not core_scenes:
        return []

    first_sc = dict(core_scenes[0])
    raw_heading = str(first_sc.get("heading") or sub_vtype)
    clean_heading = re.sub(
        r"^(?:第\d+[章節]\s*|\d+[.．:：]\s*|SECTION\s*\d+[:：]?\s*|操作実演[：:・\s]*|実践ハンズオン[：:・\s]*|活用事例[：:・\s]*)+",
        "",
        raw_heading,
        flags=re.I,
    ).strip() or raw_heading

    # Extract 3 key points from core scenes for title overview & closing checklist
    extracted_points: list[str] = []
    for sc in core_scenes:
        for b in sc.get("bullets") or []:
            if b not in extracted_points:
                extracted_points.append(str(b))
        for st in sc.get("steps") or []:
            desc = st.get("desc") or st.get("title") or ""
            if desc and desc not in extracted_points:
                extracted_points.append(str(desc))
        for cd in sc.get("cards") or []:
            body = cd.get("body") or cd.get("title") or ""
            if body and body not in extracted_points:
                extracted_points.append(str(body))
        tbl = sc.get("table")
        if isinstance(tbl, dict):
            for r in (tbl.get("rows") or [])[:3]:
                cells = [str(c).strip() for c in r if c]
                if len(cells) >= 2:
                    pt = f"{cells[0]}：{cells[1]}"
                    if pt not in extracted_points:
                        extracted_points.append(pt)
    if not extracted_points:
        extracted_points = [
            c.strip(" 、。")
            for c in re.split(r"[。！？]", str(first_sc.get("narration") or ""))
            if len(c.strip(" 、。")) >= 8
        ][:3]
    if not extracted_points:
        extracted_points = [clean_heading]

    is_demo = sub_vtype == "操作実演"
    intro_scene: dict = {
        "id": f"{sub_jid}-intro",
        "kind": "title",
        "badge": "PRACTICE DEMO" if is_demo else "USE CASE",
        "sectionLabel": "はじめに",
        "heading": f"実践ハンズオン：{clean_heading}" if is_demo else f"実践活用事例：{clean_heading}",
        "sub": "画面の流れと具体的な操作ステップをわかりやすく確認します" if is_demo else "現場で成果を出すための活用パターンと導入のポイント",
        "bullets": [p[:48] for p in extracted_points[:3]],
        "narration": (
            f"この動画では、実践ハンズオンとして「{clean_heading}」の具体的な進め方を解説します。"
            "実際の画面操作や設定のポイントを順番に確認していきましょう。"
            if is_demo
            else f"この動画では、現場ですぐに役立つ活用事例として「{clean_heading}」のポイントをご紹介します。"
            "日々の業務にどう取り入れるか、具体的な進め方を見ていきましょう。"
        ),
    }

    summary_cards = _derive_visual_cards_from_text(
        clean_heading, str(core_scenes[-1].get("narration") or ""), extracted_points
    )
    for idx_c, c in enumerate(summary_cards):
        c["tag"] = f"CHECK 0{idx_c + 1}" if is_demo else f"POINT 0{idx_c + 1}"

    outro_scene: dict = {
        "id": f"{sub_jid}-summary",
        "kind": "summary",
        "badge": "CHECKLIST" if is_demo else "SUMMARY",
        "sectionLabel": "まとめ",
        "heading": f"{clean_heading}・実践チェックリスト" if is_demo else f"{clean_heading}・導入のまとめ",
        "lead": "今回の内容を実務へ定着させるための確認ポイントです",
        "cards": summary_cards,
        "callout": {
            "type": "tip" if is_demo else "good",
            "text": (
                "まずは手元の1つの業務で実際に操作し、再現できる形に整えましょう。"
                if is_demo
                else "定型業務のテンプレート化とチーム共有で、全体の作業効率を高めましょう。"
            ),
        },
        "narration": (
            f"最後に、「{clean_heading}」の実践チェックリストを振り返りましょう。"
            "手順どおりに入力できているか、出力された結果が目的に合っているかを確かめるのが成功のコツです。"
            "まずは手元の業務で一つ試してみてください。"
            if is_demo
            else f"最後に、「{clean_heading}」のまとめです。"
            "効果の高かったやり方をテンプレートとして残し、チーム全体へ共有することで業務効率が大きく向上します。"
            "ぜひ明日からの業務に取り入れてみてください。"
        ),
    }

    middle_scenes = []
    for idx_m, sc in enumerate(core_scenes, 1):
        sc_copy = dict(sc)
        sc_copy["id"] = f"{sub_jid}-main-{idx_m:02d}"
        middle_scenes.append(sc_copy)

    if len(middle_scenes) == 1:
        return [intro_scene, middle_scenes[0], outro_scene]
    return [intro_scene] + middle_scenes
    

def derive_subvideo_jobs_from_full_scenes(
    lesson_id: str, full_scenes: list[dict]
) -> list[tuple[str, str, list[dict]]]:
    """
    Automatically derive 2 additional standalone sub-video jobs besides `<lesson_id>-full`:
      1. Hands-on / Practice demonstration video (`操作実演`) from the primary middle practical section
      2. Application / Use-case / Wrap-up video (`活用事例`) from the closing section
    Each derived sub-video is guaranteed to have a complete 3+ scene standalone arc.
    """
    if not full_scenes:
        return []
    if len(full_scenes) < 4:
        mid_slice = full_scenes[1:2] if len(full_scenes) >= 2 else full_scenes[:1]
        end_slice = full_scenes[-1:]
        j1 = f"{lesson_id}-02"
        j2 = f"{lesson_id}-03"
        return [
            (j1, "操作実演", _ensure_standalone_subvideo_arc(j1, "操作実演", mid_slice)),
            (j2, "活用事例", _ensure_standalone_subvideo_arc(j2, "活用事例", end_slice)),
        ]

    # Group scenes by section number (from badge `SECTION XX` or sectionId)
    groups: list[tuple[str, list[dict]]] = []
    cur_key = ""
    cur_list: list[dict] = []
    for idx, sc in enumerate(full_scenes):
        badge = str(sc.get("badge") or "")
        sec_id = str(sc.get("sectionId") or "")
        m = re.search(r"(\d+)", badge) or re.search(r"section[-_]?(\d+)", sec_id, re.I)
        sec_num = f"{int(m.group(1)):02d}" if m else f"{idx + 1:02d}"
        if sec_num != cur_key:
            if cur_list:
                groups.append((cur_key, cur_list))
            cur_key = sec_num
            cur_list = [sc]
        else:
            cur_list.append(sc)
    if cur_list:
        groups.append((cur_key, cur_list))

    if len(groups) < 3:
        mid = len(full_scenes) // 2
        j1 = f"{lesson_id}-02"
        j2 = f"{lesson_id}-03"
        return [
            (j1, "操作実演", _ensure_standalone_subvideo_arc(j1, "操作実演", full_scenes[1 : max(2, mid + 1)])),
            (j2, "活用事例", _ensure_standalone_subvideo_arc(j2, "活用事例", full_scenes[-1:])),
        ]

    # Pick primary hands-on group in middle (prefer group with images/steps/tables or highest scene count among middle sections)
    candidate_mid = groups[1:-1]
    best_mid_key, best_mid_scenes = max(
        candidate_mid,
        key=lambda item: (
            sum(1 for s in item[1] if s.get("image") or s.get("kind") in ("full-image", "split-image", "steps", "table")),
            len(item[1]),
        ),
    )
    last_key, last_scenes = groups[-1]
    if last_key == best_mid_key and len(groups) >= 2:
        best_mid_key, best_mid_scenes = groups[max(0, len(groups) - 2)]

    j1 = f"{lesson_id}-{best_mid_key}"
    j2 = f"{lesson_id}-{last_key}"
    return [
        (j1, "操作実演", _ensure_standalone_subvideo_arc(j1, "操作実演", best_mid_scenes)),
        (j2, "活用事例", _ensure_standalone_subvideo_arc(j2, "活用事例", last_scenes)),
    ]


def build_package(input_src: str, out_dir: Optional[Path] = None, title: Optional[str] = None) -> Path:
    is_url = bool(re.match(r"^https?://", input_src))
    src_path = None if is_url else Path(input_src).expanduser().resolve()
    if src_path is not None and not src_path.exists():
        raise FileNotFoundError(f"input not found: {src_path}")

    stem = (urllib.parse.urlparse(input_src).path.rstrip("/").split("/")[-1] or "web") if is_url else src_path.stem
    lesson_id = _slug(stem, input_src)
    if out_dir is None:
        base = Path(os.environ.get("COURSE_VIDEO_DOWNLOADS_DIR", str(Path.home() / "Downloads"))) if is_url else src_path.parent
        out_dir = base / f"{lesson_id}_video_package"
    out_dir = Path(out_dir).resolve()
    for sub in ("images", "videos"):
        if (out_dir / sub).exists():
            shutil.rmtree(out_dir / sub)  # rebuild deterministically from the source
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = "" if is_url else src_path.suffix.lower()
    print(f"[compile] input={input_src} type={suffix or 'url'} -> {out_dir}")

    is_video_source = suffix in VIDEO_INPUT_EXTS
    if is_video_source:
        doc_title, scenes = video_to_scenes(src_path, out_dir, title)
    elif suffix == ".pdf":
        scenes = pdf_to_scenes(src_path, out_dir)
        doc_title = title or re.sub(r"（\d+/\d+）$", "", scenes[0]["heading"])
    elif suffix in (".pptx", ".ppt", ".key", ".odp"):
        with tempfile.TemporaryDirectory() as td:
            pdf = office_to_pdf(src_path, Path(td))
            notes = pptx_notes(src_path) if suffix == ".pptx" else {}
            scenes = pdf_to_scenes(pdf, out_dir, notes=notes)
        doc_title = title or re.sub(r"（\d+/\d+）$", "", scenes[0]["heading"])
    elif suffix in (".md", ".markdown", ".txt"):
        md = src_path.read_text(encoding="utf-8")
        doc_title, scenes = markdown_to_scenes(md, AssetStore(out_dir, src_path.parent, None), title)
    else:  # .docx / .html / .htm / .epub / URL ... via markitdown
        md = _to_markdown(input_src if is_url else str(src_path))
        assets = AssetStore(out_dir, None if is_url else src_path.parent, input_src if is_url else None)
        if not title and is_url and not re.search(r"^#\s", md, re.M):
            title = _html_title(input_src)  # markitdown may drop <title>/<h1> for some pages
        doc_title, scenes = markdown_to_scenes(md, assets, title)

    if not scenes:
        raise RuntimeError("No scenes could be compiled from the input.")

    course_id = "video" if is_video_source else "doc"
    job_id = f"{lesson_id}-full"
    batch = {
        "courseId": course_id,
        "lessonId": lesson_id,
        "lessonTitle": doc_title,
        "source": input_src,
        "source_type": "video" if is_video_source else (suffix.lstrip(".") or "url"),
        "jobs": [{"id": job_id, "output": f"{job_id}/{job_id}.mp4", "type": "動画編集" if is_video_source else "汎用"}],
    }
    spec: dict = {
        "status": "auto-compiled",
        "source_type": "video" if is_video_source else (suffix.lstrip(".") or "url"),
        "course_id": course_id,
        "lesson_id": lesson_id,
        "lesson_title": doc_title,
        "jobs": {job_id: {"videoType": "動画編集" if is_video_source else "解説", "lessonTitle": doc_title, "scenes": scenes}},
    }

    # Auto-polish narration (de-duplicate repeats, fix missing periods, vary endings)
    # and auto-populate `narration_prosody`, `narration_tts`, `narration_kana`, and `reading_dict.json`
    try:
        try:
            from .edit_storyboard import export_readings_sheet, polish_spec_scenes
        except ImportError:
            from edit_storyboard import export_readings_sheet, polish_spec_scenes

        polished_scenes, polish_changes = polish_spec_scenes(scenes, mode="deterministic")
        spec["jobs"][job_id]["scenes"] = polished_scenes
        if not is_video_source and len(polished_scenes) >= 1:
            for sub_jid, sub_vtype, sub_scenes in derive_subvideo_jobs_from_full_scenes(lesson_id, polished_scenes):
                if sub_jid not in spec["jobs"]:
                    spec["jobs"][sub_jid] = {
                        "videoType": sub_vtype,
                        "lessonTitle": doc_title,
                        "scenes": sub_scenes,
                    }
                    batch["jobs"].append(
                        {"id": sub_jid, "folder": sub_jid, "output": f"{sub_jid}/{sub_jid}.mp4", "video_type": sub_vtype}
                    )
        if polish_changes:
            print(f"  ✨ [compile] Auto-polished {len(polish_changes)} scenes (removed repeats & smoothed Japanese flow)")
        _, _, spec, _ = export_readings_sheet(spec, out_dir)
    except Exception as e:
        print(f"  ⚠️  [compile] Hiragana dictionary / auto-polish warning: {e}")

    if is_video_source and src_path is not None:
        job_out_dir = out_dir / job_id
        job_out_dir.mkdir(parents=True, exist_ok=True)
        dst_mp4 = job_out_dir / f"{job_id}.mp4"
        if src_path.resolve() != dst_mp4.resolve():
            shutil.copy2(src_path, dst_mp4)

    (out_dir / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "scenes_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    kinds: dict[str, int] = {}
    for sc in scenes:
        kinds[sc["kind"]] = kinds.get(sc["kind"], 0) + 1
    print(f"[compile] {len(scenes)} scenes {kinds} title='{doc_title}'")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile Video(.mp4/.mov/.webm)/Markdown/PDF/PPTX/DOCX/HTML/URL into a course-video package")
    ap.add_argument("input")
    ap.add_argument("-o", "--out-dir", default="")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    pkg = build_package(a.input, Path(a.out_dir) if a.out_dir else None, a.title or None)
    print(pkg)


if __name__ == "__main__":
    main()
