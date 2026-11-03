---
name: course-video-producer
description: 教材パッケージ（batch.json / scenes_spec.json / video-job.json / video-script.md / images / assets-manifest.json）から、1コマンド（Zero-LLM・決定論的パイプライン）で自然な日本語ナレーション（Fish Audio s2-pro 清楚な若手アナウンサー調：ca8c24e05b1245c4bdbf28bfb9be5275）とRemotion（1920x1080・30fps・BT.709・画像100%表示＆自動ズーム）＋放送・配信規格マスタリング（EBU R128 -14.5 LUFS 48kHz / 日本語字幕トラック mov_text 内蔵）のMP4教材動画を高速一括生成するスキル。下位AIモデル（Gemini 3.8 Flash等）でも品質劣化ゼロで即座に完遂可能。
---

# Course Video Producer v2.0（1コマンド高速・放送局規格教材動画生成スキル）

教材エクスポートパッケージ（例：`ai-user-a01/lesson01`、`ai-user-a02/lesson02`、`ai-user-a03/lesson03` 等）から、**下位AIモデル（`Gemini 3.8 Flash Low/Medium` 等）でも一切のハルシネーションや品質劣化を起こさず、最短1コマンドで放送・YouTube配信規格12項目完全合格（1920×1080 / 30fps / BT.709 / EBU R128 `-14.5 LUFS` 48kHz / 日本語ソフト字幕内蔵）の解説動画MP4を一括生成**するための決定論的スキルです。

---

## ⚡ 最速実行プロトコル（AIモデル向け絶対規律）

ユーザーから「このパッケージ（フォルダ）から動画を作って」と指示された場合、**AIモデルは独自にPythonスクリプトやTypeScript（`.tsx`）や長大なJSONを手書きしてはいけません**。

### Step 1（これだけで完結）：決定論的パイプラインを1コマンド実行する

以下の **1コマンド** をそのまま実行してください（`--scenes-json` や `--voice-id` の指定すら不要です）：

```bash
python3 /Users/jungosakamoto/Claude/ai-ops/master_skills/content/course-video-producer/scripts/render_course_package.py \
  --package-dir "<パッケージの絶対パス>" \
  --downloads-dir "/Users/jungosakamoto/Downloads"
```

### この1コマンドが自動で行う処理（AIの推論・手作業不要）
1. **シーン定義の自動解決（4段階カスケード）**:
   - `--scenes-json` 明示指定があれば最優先適用。
   - パッケージ直下に `<package_dir>/scenes_spec.json` があれば自動検出・適用（0ms）。
   - `examples/<course_id>_<lesson_id>_scenes_spec.json` に検証済みゴールデン定義があれば自動適用（0ms）。
   - 新規レッスンでゴールデン定義がない場合も、パッケージ内の `batch.json`・各ジョブの `video-job.json`・`video-script.md`・`assets-manifest.json` を**決定論的パーサーが自動コンパイル**し、原稿100%忠実な `scenes_spec.auto.json` を自動生成します。
2. **自然な日本語ナレーション検査（`coji/natural-japanese` 連携）**:
   - 原稿内の不自然なAI常套句（「と言えるでしょう」「非常に重要」「さまざまなメリットが存在」等）を決定論的にチェックし、原文の事実を100%保持（元にない内容を足さない原則）。
   - 新規台本作成や原稿推敲時は `uv run /Users/jungosakamoto/Claude/ai-ops/master_skills/content/natural-japanese/scripts/lint.py <script.md>` で事前検査可能。
3. **画像アセットのサニタイズ＆同期**:
   - `<package_dir>/images/*` を `/Users/jungosakamoto/Claude/content/video/public/<course_id>_<lesson_id>/images/` へコピーし、`chmod 644` と `xattr -cr`（macOS隔離属性除去）を自動実行。
4. **Fish Audio `s2-pro` 並列音声合成（4並列・SHA-256キャッシュ付き）**:
   - 標準ボイス **`ca8c24e05b1245c4bdbf28bfb9be5275`**（**プロの明瞭さ × 丁寧で明るい歓迎感：清楚な若手アナウンサー調** / `sample_hybrid_1.mp3`）で、全シーンを4スレッド並列合成（2回目以降は変更シーンのみ差分合成）。
5. **Remotion フルHDレンダリング（`--concurrency=4 --timeout=120000`）**:
   - `CourseVideo` コンポジション（[`Lesson01Video.tsx`](file:///Users/jungosakamoto/Claude/content/video/src/scenes/lesson01/Lesson01Video.tsx)）で画面100%表示・注目箇所への自動スポットライト拡大（1.36倍ズーム）付き映像をレンダリング。
6. **放送・配信規格マスタリング（`kajisho5/ffmpeg-skill` 規格準拠）**:
   - **EBU R128 2パス線形ラウドネス正規化**: 音声を `-14.5 LUFS` / True Peak `-1.5 dBTP` / `48000 Hz` `192kbps` AAC へ無劣化正規化。
   - **BT.709 HD色空間刻印**: H.264ビットストリームおよびMP4コンテナに `bt709` を付与し、QuickTime / Chrome / iOS / YouTube間の色味差をゼロ化。
   - **日本語ソフト字幕トラック内蔵**: 文単位のタイムスタンプから `.srt` を自動生成し、画面内の放送デザイン字幕に加えてMP4公式字幕ストリーム（`mov_text` / `language=jpn`）を多重化。
   - `ffmpeg-skill` の `check.py --platform youtube` 全12項目（解像度・アスペクト比・FPS・CFR・コーデック・BT.709色空間・48kHz音声・日本語字幕・ラウドネス・True Peak）で **12/12 PASS（0 FAIL / 0 WARN）** を保証。
7. **全出力先への自動同期＆ZIP作成**:
   - `<package_dir>/<job_folder>/<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<course_id>_<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<course_id>_videos/<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<course_id>_videos.zip`

---

## 🎙️ 標準ナレーション音声・マスタリング仕様

| 項目 | 設定値 |
| :--- | :--- |
| **エンジン / モデル** | Fish Audio API (`https://api.fish.audio/v1/tts`) / `model: "s2-pro"` |
| **標準 `reference_id`** | **`ca8c24e05b1245c4bdbf28bfb9be5275`** （`DEFAULT_VOICE_ID`） |
| **声質プロファイル** | **プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー調）**（`sample_hybrid_1.mp3` / 著作権・商用フリー） |
| **Prosody / 生成設定** | `speed: 0.98`, `volume: 0`, `top_p: 0.8`, `temperature: 0.75`, `chunk_length: 260`, `mp3_bitrate: 192` |
| **最終音声マスタリング** | EBU R128 2-Pass Linear `loudnorm` (`I=-14.5 LUFS`, `TP=-1.5 dBTP`, `LRA=11`), AAC `48000 Hz` Stereo `192 kbps` |
| **映像色空間 / 字幕** | H.264 High `1920x1080` `30fps` CFR `bt709` + 焼き込みテロップ + `mov_text` (`jpn`) ソフト字幕 |
| **APIキー取得** | macOS Keychain (`security find-generic-password -s "FishAudio" -w`) または環境変数 `FISHAUDIO_API_KEY` |

---

## 🔗 連携スキル（GitHub Ecosystem）

- **`natural-japanese`** (`coji/natural-japanese`): ナレーション・台本のAI臭さ除去・自然化Lint（`scripts/lint.py`）
- **`ffmpeg-skill`** (`kajisho5/ffmpeg-skill`): 42種のローカルFFmpeg編集・EBU R128ラウドネス・納品QC検査（`scripts/check.py` / `scripts/loudness.py` / `scripts/look.py`）
- **`remotion-best-practices`** (`remotion-dev/skills` v4.0.540): Remotion公式Reactマークアップ・アニメーション・キャプション規約
- **`remotion-video-director`** (`BayramAnnakov/remotion-video-director`): 映像シナリオ演出・モーショングラフィックス設計パターン

---

## 🚫 下位AIモデル向け禁止事項（Anti-Failure Guardrails）

1. **原稿の勝手な創作・要約をしない**: 教材の質問例・比較対象・料金表記を別の例題に書き換えないこと（自動コンパイラおよびパッケージ内の `scenes_spec.json` をそのまま使うこと）。
2. **Remotionの `.tsx` コンポーネントを書き換えない**: 既存の [`Lesson01Video.tsx`](file:///Users/jungosakamoto/Claude/content/video/src/scenes/lesson01/Lesson01Video.tsx) が全10種類のレイアウト（`title`/`hero`, `full-image`, `split-image`, `dual-image`, `table`, `chat-sim`, `promises`/`cards`, `worksheet`, `dot-flow`）と自動ズームに対応済みです。
3. **漢字のひらがな開拓やカギ括弧除去をしない**: `render_course_package.py` 内の `S2_PRO_SAFE_REPLACEMENTS` が最適な読み補正を行います。
