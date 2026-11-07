---
name: course-video-producer
description: 教材パッケージ、または素のMarkdown・PDF・PowerPoint・Word・HTML・Web記事URL・動画ファイルから、1コマンド（Zero-LLM・決定論的パイプライン）で自然な日本語ナレーション付きMP4解説動画を生成する汎用ビデオメイキングスキル（v4.0）。scenes_spec.json自動生成時の「無駄なリピート除去・文連結補正・文末多様化（Auto-Polish）」、内蔵16,563語（現代日本語＋AI/IT専門用語）発音辞書優先＋辞書外語のひらがなテキストインストラクション自動フォールバック、音響ポーズ検出によるミリ秒単位の字幕同期＆キーワード強調（subtitleCues）、BGM＋サイドチェイン自動ダッキング＋章切替SE（--bgm / --se）、複数話者の対話レイアウト（dialogue）、アニメーション棒グラフ（chart）、UI自動ズーム＆赤枠スポットライト（focusRect / spotlights）に対応。
---

# Course Video Producer v4.0（汎用ビデオメイキング・16,563語辞書＋ひらがな指示・音響同期字幕・BGM自動ダッキング・対話＆チャート対応）

教材パッケージに加えて、**素の文書（Markdown / PDF / PPTX / DOCX / HTML / URL / MP4）をそのまま渡すだけ**で、無駄なリピートのない自然な日本語ナレーションに自動整形された `scenes_spec.json` を生成し、16:9・9:16・1:1 の解説・プロモーション・対話動画MP4を1コマンドで生成します。

> パス表記の `<SKILL_DIR>` は本スキルの配置先です（例: `~/Claude/ai-ops/master_skills/content/course-video-producer`）。

---

## ⚡ 最速実行プロトコル ＆ 常時3動画自動生成標準（AIモデル向け絶対規律）

**AIモデルは独自にPython・TSX・長大なJSONを手書きしてはいけません。** 以下のどちらか1コマンドだけを実行してください。

### 🎬 常時3動画自動生成標準（Three-Video Standard: 全ジョブ共通デフォルト）
どの入力（素の文書・スライド・教材パッケージ・1ジョブのみの `batch.json`）から実行した場合でも、パイプラインは自動的に以下の **3本のMP4動画** を生成・ZIP同梱します（`derive_subvideo_jobs_from_full_scenes` により自動派生・永続化）：
1. **① フル動画（`<lesson>-full.mp4` / `ダイジェスト`）**: 全セクションを通しで網羅する本編動画
2. **② サブ動画①（`<lesson>-XX.mp4` / `操作実演`）**: 中盤の最重要ハンズオン・画面操作セクションを抜粋した実演動画
3. **③ サブ動画②（`<lesson>-YY.mp4` / `活用事例`）**: 終盤の応用事例・まとめセクションを抜粋した活用動画
- さらに既定で **BGM自動サイドチェイン・ダッキング（`--bgm corporate-ambient`）**、**章切替チャイム（`--se`）**、**16,563語辞書優先＋ひらがなフォールバック**、**無駄なリピート除去（Auto-Polish）**、**音響ポーズ同期字幕（`subtitleCues`）**、**注釈済み画像の二重赤枠防止ガード** がすべて自動適用されます（BGM無効化は `--bgm none`、SE無効化は `--no-se`）。

### A. 素の文書・動画から作る（v4.0）
```bash
python3 <SKILL_DIR>/scripts/render_course_package.py --input "<文書・動画パス or URL>" \
  [--aspect 16:9|9:16|1:1] [--theme corporate-blue|warm-academy|emerald-fresh|sakura|mono-minimal] \
  [--bgm corporate-ambient|warm-acoustic|upbeat-tech|lofi-study|none] [--no-se]
```
- 例: `--input slides.pptx --aspect 9:16 --theme sakura --bgm upbeat-tech`（BGM＋効果音付き縦型ショート3本自動生成）
- 例: `--input https://example.com/article`（Web記事からフル動画＋操作実演＋活用事例の3本をBGM自動ダッキング付きで生成）

### B. 既存の教材パッケージから作る（従来どおり・1ジョブ記載でも自動で3動画化）
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

## ✍️ 経路C：生成後の「日本語・全体文脈」マニュアル＆AI編集（v3.1 `edit_storyboard.py`）

初回コンパイル後や動画生成後に、**「日本語の不自然さ・AI常套句」「前後シーンの文脈の繋がり（接続詞・冒頭重複）」「スライド見出し・箇条書き・ナレーション」** を人間（マニュアル）またはAIで事後編集し、変更したシーンだけを数秒で高速プレビュー・再レンダリングできます。

```bash
# 1. 全体文脈・日本語自然度の100点満点診断（AI常套句・冒頭重複・文末単調・スライド丸読みの検出）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py audit \
  --package-dir /path/to/package

# 2. 全体文脈・日本語の自動推敲（Fact Gate付き：数値・固有名詞・アセットを100%保護したまま自然化）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py polish \
  --package-dir /path/to/package --mode deterministic
# （LLMで全体文脈をリライトする場合は --mode llm --instruction "初心者向けに柔らかい語り口で"）

# 3. Markdown双方向ラウンドトリップ編集（JSONを触らずにエディタやAIで安全に全文編集）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py export-md \
  --package-dir /path/to/package
# -> 生成された storyboard.md を手動またはAIで編集後、以下で scenes_spec.json に反映：
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py import-md \
  --package-dir /path/to/package

# 4. 特定1シーンのピンポイントCLI編集 & 直前の変更をロールバック（undo）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py set-scene \
  --package-dir /path/to/package --scene 3 --narration "新しいナレーション原稿です。"
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py undo \
  --package-dir /path/to/package

# 5. ローカルブラウザGUIエディタの起動（スライド画像確認・手動編集・1クリックAI自然化・1シーン高速プレビュー）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py serve \
  --package-dir /path/to/package --port 8765

# 6. 編集した1シーンだけを約15秒で単体動画プレビュー生成（全編再レンダリング不要）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/render_course_package.py \
  --package-dir /path/to/package --job lesson01-full --only-scene 3 --downloads-dir ""

# 7. 漢字の読み方をあとからすべて「ひらがな」でインプット＆全文ひらがな読みベースで音声を更新
# (a) パッケージ内の全漢字単語リスト（reading_dict.json）と全文ひらがな読み台本（reading_sheet.md）を書き出し
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py export-readings \
  --package-dir /path/to/package
# (b) reading_sheet.md（または reading_dict.json / CSV）のひらがな読みを編集後、全シーンの narration_kana に一括反映
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py import-readings \
  --package-dir /path/to/package
# (c) CLIからワンライナーで漢字のひらがな読みを追加・上書き（全シーンに即時適用）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py set-reading \
  --package-dir /path/to/package --readings "一言=ひとこと,表にして=ひょうにして,一行=いちぎょう"

# 9. 【v3.6 標準搭載】動画生成前の「音声先行生成・イントネーション試聴＆編集ステージ」
#    （内蔵 16,563語 現代日本語＋AI/IT辞書最優先 ＋ 辞書外語はひらがなテキストインストラクション自動フォールバック）
python3 ~/Claude/ai-ops/master_skills/content/course-video-producer/scripts/edit_storyboard.py audio-check \
  --synth --package-dir /path/to/package
# -> <package>/audio_preview.html（ブラウザで全シーン連続試聴プレイヤー付き）と <package>/audio_check_sheet.md を出力
```

---

## 🧠 v3.6 3層ハイブリッド発音解決 ＆ `scenes_spec.json` 自動リピート除去パイプライン

1. **`scenes_spec.json` 自動生成＆無駄なリピート除去 (`--auto-polish` デフォルト有効)**:
   - `compile_input_to_spec.py` および `render_course_package.py` が `scenes_spec.json` を生成・読み込む際、以下を決定論的に自動補正します（数値・英字固有名詞は Invariant Fact Gate で100%保護）：
     - **文連結（句点欠落）の自動補正**: 箇条書きと本文の結合部に句点（`。`）を自動挿入。
     - **同一シーン内の重複文・重複例文の集約**: ステップ見出しと本文で同じ例文（`「...」`）や同じ説明文が2回繰り返される場合、1回に自動集約。
     - **連続する同一主語・同一フレーズの自然化**: 直後の文での主語反復を指示語（`これを`等）に置き換え、同一シーン内の「大丈夫です」等の反復を「問題ありません」「十分です」へ多様化。
     - **前後シーン間の重複文削除・連続文末の多様化**: 直前シーンと同一の文を整理し、「〜を確認しましょう。」等が連続する場合は「〜を見てみましょう。」「〜を確かめてみます。」へ変化をつけます。
     - **裸のセクション番号の話し言葉化**: `07で使った` / `07または08で` を `セクション7で使った` / `セクション7や8で` に自然化。
2. **3層ハイブリッド発音解決エンジン (`scripts/tts_dictionary.py` + `resources/tts_reading_dictionary.json`)**:
   - **第1優先（アクティブ発音変換辞書：12,181語 ＋ `reading_dict.json`）**: AI・IT・プログラミング・クラウド英語略語、英単語の日本語カタカナ読み、助数詞（1つ〜10個、1人/2人等）、日付・時刻、同形異音語（`一言=ひとこと`、`表にして=ひょうにして`、`一行=いちぎょう`等）を最優先で変換。
   - **第2優先（現代日本語一般漢字リファレンス辞書：4,401語）**: 常用漢字・動詞/形容詞活用形は、全文ひらがな化によるイントネーション崩壊を防ぐため `narration_prosody` 上で漢字表記を維持し、自然な高低アクセントを保持。
   - **第3優先（ひらがなテキストインストラクション自動フォールバック）**: 上記 **16,563語** の辞書に載っていない未知語・固有名詞が現れた場合、各シーンの `narration_tts` / `narration_kana`（ひらがなテキストインストラクション）から該当箇所のひらがな読みを自動抽出して発音を補完。
3. **v4.0 汎用ビデオメイキング機能 (`scripts/universal_video_upgrades.py` + `Lesson01Video.tsx` 全13レイアウト)**:
   - **① 音響ポーズ検出によるミリ秒単位の字幕同期＆キーワードハイライト (`subtitleCues`)**: FFmpeg `silencedetect` で合成音声の実際の息継ぎ（無音区間）を検出し、各文の発話開始・終了フレームを正確にアライメント。カギ括弧や数値・専門用語を字幕内でイエローハイライト表示します。
   - **② BGM自動生成・効果音（SE）＆ サイドチェイン自動ダッキング (`--bgm`, `--se`)**: 4種のアンビエントBGM（`corporate-ambient`, `warm-acoustic`, `upbeat-tech`, `lofi-study`）と章切替チャイムSEを内蔵。FFmpeg `sidechaincompress` により、ナレーターが話している間だけBGMを自動減衰させます。
   - **③ 複数話者の掛け合い・対話モード (`kind: "dialogue"`)**: `dialogue: [{"speaker": "講師", "role": "host", "text": "..."}, {"speaker": "受講生", "role": "guest", "text": "..."}]` を指定すると、話者ごとに異なる声（`--voice-id` / `--guest-voice-id`）で合成し、300msの自然な会話間（ま）を挟んで発話中スピーカーがアクティブ発光する対話画面を描画します。
   - **④ 画面操作の自動ズーム＆赤枠スポットライト (`focusRect` / `spotlights` 自動推論)**: ナレーション中の「右上」「左上」「左下」「右下」「画面中央」「画面下部」などのUI指示語を自動検出し、該当領域への1.36倍スムーズズームと赤枠パルス＆ラベルを自動付与します。
   - **⑤ アニメーション棒グラフ・KPIチャート (`kind: "chart"`)**: `chartData` を指定すると、数値カウントアップとイージングアニメーション付きの棒グラフ・比較メーターを描画します。
   - **⑥ チャプター区切り付きプログレスバー**: 画面下部の進行バーにシーン/チャプター境界のティック（区切り線）を表示します。

---

## 🛠️ 共通の自動処理（A/B/C共通）

1. シーン定義の解決（`--scenes-json` → パッケージ内 `scenes_spec.json` → `examples/` → 自動コンパイラ）＋ **自動リピート除去・日本語自然化推敲 (`--auto-polish`)**
2. 日本語AI常套句・重複リピート診断（`edit_storyboard.py audit` 100点満点スコアカード準拠）
3. 画像・動画アセットを Remotion `public/` へ同期（macのみ `xattr -cr`）
4. TTS 4並列合成（SHA-256キャッシュ）＆ **内蔵16,563語辞書優先＋ひらがなテキストインストラクション自動フォールバック＋`[ ]`/`［ ］` 括弧内タグの読み上げ完全除外**、シーン尺に合わせた無音パディングで音ズレ累積を防止
5. Remotion レンダリング（`--concurrency=4 --timeout=120000 --color-space=bt709`、または `--reuse-silent-video` で既存映像を再利用）
6. マスタリング（[kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) 規格: EBU R128 -14.5 LUFS / TP -1.5 dBTP / 48kHz AAC、BT.709タグ、**画面下部の紺色背景キャプション `SubtitleBar` のみを残し、二重表示の原因となる `mov_text` ソフト字幕はデフォルト非埋め込み**［必要な場合のみ `--embed-soft-subs`］）と ffprobe 解像度検証
7. 出力: `<package>/<job>/<job>.mp4`、`<Downloads>/<course>_<job>.mp4`、`<Downloads>/<course>_videos.zip`

---

## 🚫 下位AIモデル向け禁止事項

1. **原稿の創作・要約をしない**: 自動コンパイラの出力をそのまま使う。修正が必要なら元の文書を直すか、Markdownの `<!-- narration: ... -->` を使う。
2. **Remotionの `.tsx` を書き換えない**: `Lesson01Video.tsx` は11レイアウト（`title`/`hero`, `full-image`, `split-image`, `dual-image`, `table`, `chat-sim`, `promises`/`cards`, `worksheet`, `dot-flow`, `video-clip`）・3アスペクト・5テーマに対応済み。
3. **読み替え辞書を勝手に増やさない**: `S2_PRO_SAFE_REPLACEMENTS` が読み補正を担当。

## 🌐 事後編集・ひらがな読みベース制御・外部リモートアクセス (`edit_storyboard.py`)

```bash
# 1. 全漢字のひらがな読みシート出力・一括インポート
python3 scripts/edit_storyboard.py export-readings --package-dir /path/to/lesson01
python3 scripts/edit_storyboard.py import-readings --package-dir /path/to/lesson01

# 2. 同一Wi-Fi / スマホ・タブレットからアクセス (LAN公開 + トークン認証)
python3 scripts/edit_storyboard.py serve --package-dir /path/to/video_root --host 0.0.0.0

# 3. 外出先・外部ネットワークからHTTPSアクセス (Cloudflare Quick Tunnel + トークン認証)
python3 scripts/edit_storyboard.py serve --package-dir /path/to/video_root --tunnel

# 4. サーバー不要の単一HTMLポータブルWebアプリ出力 (Google Drive / GitHub Pages / スマホ単体で編集可能)
python3 scripts/edit_storyboard.py export-webapp --package-dir /path/to/video_root --out /path/to/studio_portable.html
```

## ⚠️ 既知の限界

- PDFはテキスト層のない画像PDFだとナレーションが見出しだけになる（OCRは行わない）。
- PDF/スライドのページテキストは箇条書きの断片が多く、話し言葉としては硬い。PPTXはスピーカーノートを書くと品質が大きく上がる。
- 縦型・正方形は16:9ステージを縮小するため、ステージ内の小さな文字はスマホでは読みにくい（大見出し・要点・字幕で補う設計）。
- 字幕の切り替えは文字数比例で、実音声と最大1秒程度ずれることがある。
