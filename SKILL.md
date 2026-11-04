---
name: course-video-producer
description: 教材パッケージ、または素のMarkdown・PDF・PowerPoint・Word・HTML・Web記事URLから、1コマンド（Zero-LLM・決定論的パイプライン）で自然な日本語ナレーション付きMP4解説動画を生成するスキル。音声は Fish Audio s2-pro（清楚な若手アナウンサー調：ca8c24e05b1245c4bdbf28bfb9be5275）を標準とし、キーがない環境では edge-tts / macOS say へ自動フォールバックする。16:9・9:16縦型ショート・1:1、5種のブランドテーマ、画面録画クリップ埋め込み（video-clip）に対応。放送・配信規格マスタリング（BT.709 / EBU R128 -14.5 LUFS 48kHz / 日本語字幕トラック）付き。下位AIモデルでも品質劣化なく完遂可能。
---

# Course Video Producer v3.0（汎用入力・マルチフォーマット・移植性対応）

教材パッケージに加えて、**素の文書（Markdown / PDF / PPTX / DOCX / HTML / URL）をそのまま渡すだけ**で、16:9・9:16・1:1 の解説動画MP4を1コマンドで生成します。原稿の内容は書き換えず、見出し・本文・スピーカーノート・ページテキストをそのままナレーションに使います。

> パス表記の `<SKILL_DIR>` は本スキルの配置先です（例: `~/Claude/ai-ops/master_skills/content/course-video-producer`）。

---

## ⚡ 最速実行プロトコル（AIモデル向け絶対規律）

**AIモデルは独自にPython・TSX・長大なJSONを手書きしてはいけません。** 以下のどちらか1コマンドだけを実行してください。

### A. 素の文書から作る（v3.0）
```bash
python3 <SKILL_DIR>/scripts/render_course_package.py --input "<文書パス or URL>" \
  [--aspect 16:9|9:16|1:1] [--theme corporate-blue|warm-academy|emerald-fresh|sakura|mono-minimal]
```
- 例: `--input slides.pptx --aspect 9:16 --theme sakura`（縦型ショート）
- 例: `--input https://example.com/article`（Web記事を解説動画化）

### B. 既存の教材パッケージから作る（従来どおり）
```bash
python3 <SKILL_DIR>/scripts/render_course_package.py --package-dir "<パッケージの絶対パス>"
```

---

## 📥 入力別の変換方式（`scripts/compile_input_to_spec.py`）

| 入力 | 使用ツール（GitHub） | シーンの作り方 | ナレーションの出所 |
| :--- | :--- | :--- | :--- |
| `.md` / `.txt` | 内蔵パーサー | `#`=タイトル、`##`/`###`=1シーン。表→`table`、画像→`full-image`/`split-image`/`dual-image`、動画リンク→`video-clip` | 段落本文（なければ箇条書き）。`<!-- narration: ... -->` で上書き可 |
| `.pdf` | poppler `pdftoppm` / `pdftotext` | 1ページ=1シーン（全画面画像） | ページのテキスト層 |
| `.pptx` / `.ppt` / `.key` | LibreOffice headless → PDF、[microsoft/markitdown](https://github.com/microsoft/markitdown) | 1スライド=1シーン | **スピーカーノート優先**、なければスライド本文 |
| `.docx` / `.html` / URL | [microsoft/markitdown](https://github.com/microsoft/markitdown)（`doc-to-md`） | Markdownに変換後、上と同じ | 段落本文 |

- 700文字を超えるセクションは文の切れ目で「（1/2）」のように自動分割します。
- 生成物は `<入力と同じ階層>/<slug>_video_package/`（URLは `~/Downloads/`）に `batch.json` / `scenes_spec.json` / `images/` / `videos/` として保存され、`--package-dir` で再レンダリングや手修正ができます。

---

## 🎨 表現フォーマット

- **`--aspect`**: `16:9`（1920×1080・従来レイアウト）/ `9:16`（1080×1920）/ `1:1`（1080×1080）。縦型・正方形は、検証済みの16:9ステージを幅いっぱいに縮小配置し、上に大見出し、下に大きな要点と字幕を置きます（既存10レイアウトを書き換えないので回帰リスクが低い）。
- **`--theme`**: `corporate-blue`（既定）/ `warm-academy` / `emerald-fresh` / `sakura` / `mono-minimal`。主色だけを差し替え、緑・黄・赤などの意味色は維持します。
- **`video-clip` シーン**: 画面録画や実写（`.mp4/.mov/.webm/.m4v`）を `<OffthreadVideo>` で無音再生。ナレーションより長い場合は最大2倍速、それでも長ければシーンを延長し音声に無音を足して同期を保ちます。短い場合は最終フレームで静止します。

---

## 🎙️ 音声（`--tts auto|fish|edge|say`）

| プロバイダ | 条件 | 声 |
| :--- | :--- | :--- |
| `fish`（標準） | `FISHAUDIO_API_KEY` または macOS Keychain `FishAudio` | `ca8c24e05b1245c4bdbf28bfb9be5275`（s2-pro・清楚な若手アナウンサー調） |
| `edge` | [rany2/edge-tts](https://github.com/rany2/edge-tts) がインストール済み | `ja-JP-NanamiNeural`（`COURSE_VIDEO_EDGE_VOICE`） |
| `say` | macOS | `Kyoko`（`COURSE_VIDEO_SAY_VOICE`） |

- `auto`（既定）は fish → edge → say の順に選び、フォールバック時は **⚠️ 警告をログに出します**（標準ボイスと声が変わるため、納品物では `--tts fish` を明示推奨）。
- `edge` はナレーション本文を Microsoft のオンラインTTSに送信します。機密原稿では `fish` か `say` を使ってください。
- 有料APIへの自動フォールバックはしません。

---

## 🔧 移植性（環境変数）

| 変数 | 既定値 | 用途 |
| :--- | :--- | :--- |
| `COURSE_VIDEO_REMOTION_ROOT` | 同梱 `remotion/`（npm install済みなら）→ `~/Claude/content/video` | Remotionプロジェクト |
| `COURSE_VIDEO_DOWNLOADS_DIR` | `~/Downloads` | コピー・ZIP出力先（`--downloads-dir ""` で無効） |
| `FISHAUDIO_API_KEY` | （Keychainはmacのみ参照） | Fish Audio キー |

---

## 🛠️ 共通の自動処理（A/B共通）

1. シーン定義の解決（`--scenes-json` → パッケージ内 `scenes_spec.json` → `examples/` → 自動コンパイラ）
2. 日本語AI常套句チェック（[coji/natural-japanese](https://github.com/coji/natural-japanese) 準拠・原文は変更せず警告のみ）
3. 画像・動画アセットを Remotion `public/` へ同期（macのみ `xattr -cr`）
4. TTS 4並列合成（SHA-256キャッシュ。Fishの既存キャッシュはv2と互換）、シーン尺に合わせた無音パディングで音ズレ累積を防止
5. Remotion レンダリング（`--concurrency=4 --timeout=120000`）
6. マスタリング（[kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) 規格: EBU R128 -14.5 LUFS / TP -1.5 dBTP / 48kHz AAC、BT.709タグ、日本語 `mov_text` 字幕）と ffprobe 解像度検証
7. 出力: `<package>/<job>/<job>.mp4`、`<Downloads>/<course>_<job>.mp4`、`<Downloads>/<course>_videos.zip`

---

## 🚫 下位AIモデル向け禁止事項

1. **原稿の創作・要約をしない**: 自動コンパイラの出力をそのまま使う。修正が必要なら元の文書を直すか、Markdownの `<!-- narration: ... -->` を使う。
2. **Remotionの `.tsx` を書き換えない**: `Lesson01Video.tsx` は11レイアウト（`title`/`hero`, `full-image`, `split-image`, `dual-image`, `table`, `chat-sim`, `promises`/`cards`, `worksheet`, `dot-flow`, `video-clip`）・3アスペクト・5テーマに対応済み。
3. **読み替え辞書を勝手に増やさない**: `S2_PRO_SAFE_REPLACEMENTS` が読み補正を担当。

## ⚠️ 既知の限界

- PDFはテキスト層のない画像PDFだとナレーションが見出しだけになる（OCRは行わない）。
- PDF/スライドのページテキストは箇条書きの断片が多く、話し言葉としては硬い。PPTXはスピーカーノートを書くと品質が大きく上がる。
- 縦型・正方形は16:9ステージを縮小するため、ステージ内の小さな文字はスマホでは読みにくい（大見出し・要点・字幕で補う設計）。
- 字幕の切り替えは文字数比例で、実音声と最大1秒程度ずれることがある。
