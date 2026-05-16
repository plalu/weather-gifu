# weather-gifu 開発メモ・振り返り

> 2026-05-11 作成。クラウド運用を再検討する際の参考資料。

## 現在の構成（採用版）

**N100 ローカル + Drive 中継方式**

```
N100 (常時稼働・住宅IP)
  ├ Windows タスクスケジューラ (毎朝)
  ├ python main.py 実行
  │   ├ 気象庁API (210000) → 天気/気温/降水確率
  │   ├ Groq or Cerebras API → AIアドバイス生成
  │   └ TTS Quest VOICEVOX API → WAV合成
  │
  ├ G:\マイドライブ\weather\today.wav に書き出し
  └ Google Drive for Desktop が自動同期
       ↓
Google Drive クラウド
       ↓
Android (MacroDroid 7:30 起動)
  ├ HTTPリクエスト → Driveの直接DLリンクから today.wav 取得
  └ サウンド再生 (春日部つむぎ)
```

採用理由：
- N100は日本の住宅IPなので Groq/Cerebras が動く
- 既存の Google Drive 連携を活かせる
- MacroDroid 無料版でも HTTP リクエストアクションで対応可能

---

## クラウド版（GitHub Actions）を断念した理由

### 致命的問題：AI API の IP ブロック

**症状**：GitHub Actions から Groq / Cerebras の無料枠 API を叩くと 403 Forbidden。
ローカル(日本IP)から同じキーで叩くと 200 OK。

**原因**：両社とも無料枠は Azure / AWS などクラウド DC の IP からのアクセスをブロック。
無料枠の不正利用防止策と思われる（業界全体の傾向）。

**確認した範囲**：
- ❌ Groq (`llama-3.3-70b-versatile`)
- ❌ Cerebras (`qwen-3-235b-a22b-instruct-2507`)
- 未検証：Gemini API、GitHub Models、Mistral、Cohere

### 残ったクラウド版コード（無効化済）

- `.github/workflows/morning.yml` ─ Disabled 状態で残置（Enable で復活可）
- ルールベースアドバイスでフォールバックすれば動作はする
- ただし AI なしだと「メッシュジャケットと薄手グローブで快適に走れます」程度の定型文

---

## クラウド版を復活させる場合の選択肢

優先度順：

### A. GitHub Models（最有力）

GitHub 純正の無料 AI 推論サービス。

- 料金：無料（個人）
- 認証：`secrets.GITHUB_TOKEN` 自動付与、APIキー登録不要
- モデル：`openai/gpt-4o-mini`、Llama 3.3 70B、Phi、Mistral 等
- API形式：OpenAI 互換
- エンドポイント：`https://models.inference.ai.azure.com/chat/completions`
- IPブロック問題：なし（GitHub 内部サービス）

ワークフロー追加設定：
```yaml
permissions:
  models: read
```

### B. Google Gemini API

- 無料枠：Gemini Flash で 1500req/日
- クラウドIPでも通る可能性高
- 公式SDKあり

### C. Cloudflare Workers AI

- 無料枠あり、Llama/Qwen 系利用可
- Workers でなく REST API でも叩ける

### D. 有料プラン (Groq / Cerebras / OpenAI)

月 $5〜程度の少額課金で IP制限が消える。

---

## 既知のバグ・落とし穴メモ

### JMA API 関連

1. **岐阜県のエリアコード = `210000`**（東海地方ではない）
2. **「岐阜地方」は存在しない**。実際は「美濃地方」「飛騨地方」。
   `next(...) or areas[0]` で美濃地方にフォールバックしている。
3. **早朝実行時、`forecast[0]` から今日の最低気温が消える**ことがある。
   `forecast[1]` 週間予報の `tempsMin`/`tempsMax` を**日付フィルタなし**で先頭エントリ取得が必要。
4. 時刻 `T09:00:00+09:00` が最高気温、`T00:00:00+09:00` が最低気温。
   `hour < 9` で最低、`hour >= 9` で最高（≦ にすると逆転バグ発生）。

### TTS Quest API 関連

5. **同期生成ではなく非同期**。`audioStatusUrl` を `isAudioReady=true` までポーリング必須。
6. **GET 直叩きでは WAV は返ってこない**。レスポンスJSONの `wavDownloadUrl` から別途DL。
7. **同一テキストはサーバー側キャッシュ**（同じテキストなら2回目以降は即時返却）。

### GitHub Actions 関連

8. **cron は UTC**。`'25 21 * * *'` で JST 06:25 起動。
9. **最大 15 分の遅延あり**。クリティカルな時刻指定は要バッファ。
10. **Node.js 20 deprecation 警告**は無視可（2026年6月以降に Node.js 24 へ移行）。

### GitHub Secret 関連

11. **登録後は中身を再確認できない**。設定ミス疑い時はワークフローで `len()` `head/tail` をログ出力して切り分け。
12. **重要操作時は sudo mode** が発動、メール認証が必要。

---

## 残課題・改善アイデア

### すぐできる改善

- [ ] **生成失敗時の通知**：失敗時に Slack/LINE/メール通知（前日WAV再生を防ぐ）
- [ ] **メタデータ同時出力**：`today.json` に生成時刻を入れ、MacroDroid側で当日チェック
- [ ] **温度サニティチェック**：気温が -10℃ 未満 / 50℃ 超なら警告（JMAパースバグ早期発見）
- [ ] **GROQ_API_KEY / CEREBRAS_API_KEY をローカル環境変数化**して `main.py` からハードコード除去

### 中長期改善

- [ ] **VOICEVOX をN100ローカル直接実行**（TTS Quest 依存をなくす）
- [ ] **複数AI のフォールバックチェーン**：Cerebras → Groq → Gemini → ルールベース
- [ ] **GitHub Models を一度試して動くか確認**（クラウド再挑戦用）
- [ ] **N100 で Ollama + Qwen 2.5 3B Q4_K_M** をフォールバック用に常駐（クラウドAPI全滅時の保険）

---

## ファイル構成

```
weather-gifu/
├ main.py                       # メインスクリプト（標準ライブラリのみ）
├ requirements.txt              # 空（追加依存なし）
├ .gitignore                    # *.wav, __pycache__, .env
├ .github/workflows/morning.yml # GitHub Actions（現在 Disabled）
├ NOTES.md                      # このファイル
└ README.md                     # GitHub 自動生成
```

## 環境変数

| 名前 | 用途 | 必須 |
|---|---|---|
| `OUTPUT_PATH` | WAV保存先 | デフォルト `today.wav`、運用時は Drive パス指定 |
| `CEREBRAS_API_KEY` | Cerebras 認証 | 任意（無ければルールベースにフォールバック） |
| `GROQ_API_KEY` | Groq 認証（旧、現コードでは未使用） | 不要 |
