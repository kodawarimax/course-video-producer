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


# ---------------------------------------------------------------------------
# Markdown -> scenes
# ---------------------------------------------------------------------------
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
        narration = override or _join_sentences(paragraphs) or _join_sentences(quotes) or _join_sentences(bullets)
        if not narration and tables:
            t = tables[0]
            narration = _join_sentences([" ".join(r) for r in [t["headers"]] + t["rows"][:3]])
        if not narration:
            narration = _join_sentences([heading])

        is_title = not scenes and (sec["level"] == 1 or si == 0)
        img_refs = [r for r in (assets.add(x, "images") for x in images[:2]) if r]
        vid_ref = assets.add(videos[0], "videos") if videos else None

        scene: dict = {"heading": heading, "sectionLabel": heading}
        if is_title:
            scene.update({"kind": "title", "sub": paragraphs[0][:80] if paragraphs else "", "badge": "INTRODUCTION"})
            if bullets:
                scene["bullets"] = bullets[:4]
            if img_refs:
                scene["image"] = img_refs[0]
        else:
            sec_no += 1
            scene["badge"] = f"SECTION {sec_no:02d}"
            if vid_ref:
                scene.update({"kind": "video-clip", "video": vid_ref})
                if paragraphs:
                    scene["videoCaption"] = paragraphs[0][:90]
            elif tables:
                scene.update({"kind": "table", "table": tables[0]})
                if img_refs:
                    scene["image"] = img_refs[0]
            elif len(img_refs) >= 2:
                scene.update({"kind": "dual-image", "image": img_refs[0], "secondImage": img_refs[1]})
            elif img_refs and bullets:
                scene.update({"kind": "split-image", "image": img_refs[0], "bullets": bullets[:5]})
            elif img_refs:
                scene.update({"kind": "full-image", "image": img_refs[0]})
            else:
                pts = bullets[:5] or [x for x in re.split(r"(?<=[。！？])", narration) if x.strip()][:4]
                scene.update({"kind": "split-image", "bullets": [p[:70] for p in pts]})
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
        first = next((l.strip() for l in raw.splitlines() if l.strip()), "")
        heading = _clean_inline(first)[:40] or f"ページ {i}"
        narration = (notes or {}).get(i) or _clean_page_text(raw)
        if not narration:
            narration = f"{heading}。"
            print(f"  ⚠️  page {i}: no text layer/notes -> narration is heading only")
        chunks = _split_long(narration)
        for ci, chunk in enumerate(chunks):
            scenes.append({
                "kind": "title" if i == 1 and ci == 0 else "full-image",
                "heading": heading if len(chunks) == 1 else f"{heading}（{ci + 1}/{len(chunks)}）",
                "sectionLabel": f"ページ {i}",
                "badge": f"PAGE {i:02d}",
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
# entry
# ---------------------------------------------------------------------------
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

    if suffix == ".pdf":
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

    course_id = "doc"
    job_id = f"{lesson_id}-full"
    batch = {
        "courseId": course_id,
        "lessonId": lesson_id,
        "lessonTitle": doc_title,
        "source": input_src,
        "jobs": [{"id": job_id, "output": f"{job_id}/{job_id}.mp4", "type": "汎用"}],
    }
    spec = {
        "status": "auto-compiled",
        "course_id": course_id,
        "lesson_id": lesson_id,
        "lesson_title": doc_title,
        "jobs": {job_id: {"videoType": "解説", "lessonTitle": doc_title, "scenes": scenes}},
    }
    (out_dir / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "scenes_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    kinds: dict[str, int] = {}
    for sc in scenes:
        kinds[sc["kind"]] = kinds.get(sc["kind"], 0) + 1
    print(f"[compile] {len(scenes)} scenes {kinds} title='{doc_title}'")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile Markdown/PDF/PPTX/DOCX/HTML/URL into a course-video package")
    ap.add_argument("input")
    ap.add_argument("-o", "--out-dir", default="")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    pkg = build_package(a.input, Path(a.out_dir) if a.out_dir else None, a.title or None)
    print(pkg)


if __name__ == "__main__":
    main()
