---
name: course-video-producer
description: 教材パッケージ（batch.json / video-job.json / video-script.md / images / assets-manifest.json）から、1コマンド（Zero-LLM・決定論的パイプライン）でFish Audio s2-pro音声（清楚な若手アナウンサー調：ca8c24e05b1245c4bdbf28bfb9be5275）とRemotion（1920x1080・30fps・画像100%表示＆自動ズーム対応）のMP4教材動画を高速一括生成するスキル。下位AIモデル（Gemini 3.8 Flash等）でも品質劣化ゼロで即座に完遂可能。
---

# Course Video Producer（1コマンド高速・決定論的教材動画生成スキル）

教材エクスポートパッケージ（例：`lesson01`、`lesson01 2`、`lesson02` 等）から、**下位AIモデル（`Gemini 3.8 Flash Low/Medium` 等）でも一切のハルシネーションや品質劣化を起こさず、最短1コマンドでフルHD（1920×1080 / 30fps）の解説動画MP4を一括生成**するための決定論的スキルです。

---

## ⚡ 最速実行プロトコル（AIモデル向け絶対規律）

ユーザーから「このパッケージ（フォルダ）から動画を作って」と指示された場合、**AIモデルは独自にPythonスクリプトやTypeScript（`.tsx`）や長大なJSONを手書きしてはいけません**。

### Step 1（これだけで完結）：決定論的パイプラインを1コマンド実行する

以下の **1コマンド** をそのまま実行してください（`--scenes-json` や `--voice-id` の指定すら不要です）：

```bash
python3 /Users/jungosakamoto/Claude/ai-ops/master_skills/content/course-video-producer/scripts/render_course_package.py \
  --package-dir "<パッケージの絶対パス>"
```

**実行例（`lesson01 2` の場合）**:
```bash
python3 /Users/jungosakamoto/Claude/ai-ops/master_skills/content/course-video-producer/scripts/render_course_package.py \
  --package-dir "/Users/jungosakamoto/Downloads/lesson01 2"
```

### この1コマンドが自動で行う処理（AIの推論・手作業不要）
1. **シーン定義の自動解決（3段階カスケード）**:
   - `examples/<lesson_id>_scenes_spec.json` に検証済みゴールデン定義があれば自動適用（0ms）。
   - 新規レッスン（`lesson02` 等）でゴールデン定義がない場合も、パッケージ内の `batch.json`・各ジョブの `video-job.json`（`pdf_spec.opening` / `scenario_sections`）・`video-script.md`（表・箇条書き）・`assets-manifest.json` を**決定論的パーサーが自動コンパイル**し、原稿100%忠実な `scenes_spec.auto.json` を自動生成します。
2. **画像アセットのサニタイズ＆同期**:
   - `<package_dir>/images/*` を `/Users/jungosakamoto/Claude/content/video/public/<lesson_id>/images/` へコピーし、`chmod 644` と `xattr -cr`（macOS隔離属性除去）を自動実行。
3. **Fish Audio `s2-pro` 並列音声合成（4並列・SHA-256キャッシュ付き）**:
   - 標準ボイス **`ca8c24e05b1245c4bdbf28bfb9be5275`**（**プロの明瞭さ × 丁寧で明るい歓迎感：清楚な若手アナウンサー調** / `sample_hybrid_1.mp3`）で、全シーンを4スレッド並列合成（2回目以降は変更シーンのみ差分合成）。
4. **Remotion フルHD高速レンダリング（6並列）＆ FFmpeg 厳格Mux**:
   - `CourseVideo` コンポジション（[`Lesson01Video.tsx`](file:///Users/jungosakamoto/Claude/content/video/src/scenes/lesson01/Lesson01Video.tsx)）で100%画面表示・注目箇所への自動スポットライト拡大（1.36倍ズーム）付き映像をレンダリング。
   - `ffmpeg -map 0:v:0 -map 1:a:0` で映像と音声を確実に結合し、`ffprobe` で映像・音声ストリームを自動検証。
5. **全出力先への自動同期＆ZIP作成**:
   - `<package_dir>/<job_folder>/<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<lesson_id>_videos/<job_id>.mp4`
   - `/Users/jungosakamoto/Downloads/<package_name>_videos.zip`

---

## 🎙️ 標準ナレーション音声仕様（統一ボイス）

| 項目 | 設定値 |
| :--- | :--- |
| **エンジン / モデル** | Fish Audio API (`https://api.fish.audio/v1/tts`) / `model: "s2-pro"` |
| **標準 `reference_id`** | **`ca8c24e05b1245c4bdbf28bfb9be5275`** （`DEFAULT_VOICE_ID`） |
| **声質プロファイル** | **プロの明瞭さ × 丁寧で明るい歓迎感（清楚な若手アナウンサー調）**（`sample_hybrid_1.mp3` / 著作権・商用フリー） |
| **Prosody / 生成設定** | `speed: 0.98`, `volume: 0`, `top_p: 0.8`, `temperature: 0.75`, `chunk_length: 260`, `mp3_bitrate: 192` |
| **APIキー取得** | macOS Keychain (`security find-generic-password -s "FishAudio" -w`) または環境変数 `FISHAUDIO_API_KEY` |

---

## 🎨 Remotion テンプレート種別（`kind`）一覧（カスタマイズ時のみ参照）

特定のスライドのみレイアウトを微調整したい場合は、`<package_dir>/scenes_spec.auto.json` または `examples/<lesson_id>_scenes_spec.json` の `kind` を編集して `--scenes-json` に渡せます。

- `"full-image"`: 画面ほぼ100%（高さ735px・余白最小）で教材図解や操作画面を大きく表示し、`spotlights` 指定時は全体表示（約1.5秒）後に注目箇所へ自動ズーム（1.36倍）。
- `"split-image"`: 左42%に要点カード、右58%に大型画像＋`spotlights`自動ズーム。
- `"dual-image"`: 2枚の教材画像を左右均等（高さ540px）に大きく並列比較。
- `"steps"`: 左側にステップ手順、右58%に操作スクリーンショット＋`spotlights`自動ズーム。
- `"table"`: Markdownの比較表を美しいバッジ付きテーブルで描画（右半分に画像併用可）。
- `"hero"` / `"cards"` / `"checklist"` / `"worksheet"` / `"chat-sim"` / `"dot-flow"`: 導入・カード整理・チェックリスト・ワークシート・チャット例・フロー図。

---

## 🚫 下位AIモデル向け禁止事項（Anti-Failure Guardrails）

1. **原稿の勝手な創作・要約をしない**: 教材の質問例・比較対象・料金表記を別の例題に書き換えないこと（自動コンパイラおよびゴールデンJSONをそのまま使うこと）。
2. **Remotionの `.tsx` コンポーネントを書き換えない**: 既存の [`Lesson01Video.tsx`](file:///Users/jungosakamoto/Claude/content/video/src/scenes/lesson01/Lesson01Video.tsx) が全10種類のレイアウトと自動ズームに対応済みです。
3. **漢字のひらがな開拓やカギ括弧除去をしない**: `render_course_package.py` 内の `S2_PRO_SAFE_REPLACEMENTS` が最適な読み補正を行います。
