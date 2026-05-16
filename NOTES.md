# weather-gifu 開発メモ・振り返り

> 2026-05-11 作成 / 2026-05-16 大規模更新（クラウド版リベンジ成功）

## 現在の構成（採用版・2026-05-16〜）

**GitHub Actions + GitHub Models + GitHub Releases 配信方式**

```
GitHub Actions (毎朝 06:25 JST = 21:25 UTC cron)
  ├ python main.py 実行
  │   ├ 気象庁API (210000) → 天気/気温/降水確率
  │   ├ GitHub Models (openai/gpt-4o-mini) → AIアドバイス生成
  │   └ TTS Quest VOICEVOX API → WAV合成
  │
  └ gh release create today today.wav (上書き)
       ↓
GitHub Releases (固定URL)
  https://github.com/plalu/weather-gifu/releases/download/today/today.wav
       ↓
Android (MacroDroid 7:30 起動)
  ├ HTTPリクエスト → 上記URLから today.wav 取得
  └ サウンド再生 (ずんだもん)
```

採用理由：
- **GitHub Models は GITHUB_TOKEN だけで動く**（IPブロックの心配なし、APIキー登録不要）
- 配信URLが固定で MacroDroid 側の設定変更が不要
- ローカルマシン常時稼働の必要なし（GitHub Actions が代行）
- 月額コスト 0 円

---

## 旧構成（停止中・2026-05-16 で凍結）

**N100 ローカル + Google Drive 中継方式**

- ファイル：`C:\Users\main\weather_gifu.py`
- タスク：`VOICEVOX_AutoStart`(6:25) / `WeatherGifu_Daily`(6:30) → **どちらも Disabled**
- 出力：`G:\マイドライブ\weather\today.wav`
- AIチェーン：Groq → Cerebras → Gemini → ルールベース（4段）
- 追加機能：走行ハザード4種（凍結・強風・濡れ路面・熱中症）、wind_correction substring バグ修正

スクリプト・タスク・WAVファイルはすべて保持。下記コマンドで即復活可能：

```powershell
schtasks /Change /TN "VOICEVOX_AutoStart" /ENABLE
schtasks /Change /TN "WeatherGifu_Daily" /ENABLE
```

ローカル版で実装したハザード4種と wind_correction バグ修正はクラウド版に未移植。
品質向上が必要になったら移植検討。

---

## クラウド版リベンジの経緯（2026-05-16）

### 一度断念した原因（旧記録）

GitHub Actions から Groq / Cerebras の無料枠 API を叩くと 403 Forbidden。
両社とも無料枠は Azure / AWS など**クラウドDCのIPからのアクセスをブロック**。
ローカル(日本住宅IP)から同じキーで叩けば 200 OK。

### 解決策：GitHub Models へ全面移行

GitHub 純正の無料AI推論サービス。**workflowのGITHUB_TOKENで認証**するため IP制限の対象外。

実装差分（コミット `bfd9f41`）：
- `cerebras_advice` → `github_models_advice` に書き換え
- エンドポイント：`https://models.github.ai/inference/chat/completions`
- モデル：`openai/gpt-4o-mini`（日本語品質良好・無料枠でも余裕の rate limit）
- ワークフロー：`permissions: models: read` を追加、`CEREBRAS_API_KEY` env を `GITHUB_TOKEN` に置換
- 不要になった secret `CEREBRAS_API_KEY` は残置可（再利用時に備える）

### 動作確認結果（2026-05-16 14:34 JST 手動実行）

- ✅ workflow run `25953970322` success
- ✅ today.wav 1.76 MB 生成
- ✅ Release `today` 上書き完了

---

## 他のクラウドAI候補（万一の予備）

GitHub Models が落ちた・廃止された場合の選択肢。

| 候補 | 無料枠 | IP制限 | 備考 |
|---|---|---|---|
| Google Gemini API | Flash 1500req/日 | なし | 公式SDKあり |
| Cloudflare Workers AI | あり | なし | Llama/Qwen 系 |
| Groq / Cerebras | あり | **クラウドDC不可** | 有料化(月$5〜)で解除可 |
| Ollama on N100 | 無制限 | N/A | ローカルなので機材必要 |

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
10. **長期間 push のないリポジトリは workflow が自動 disable** される場合あり。
    `disabled_manually` 状態になったら手動で再 enable が必要。

### GitHub Secret 関連

11. **登録後は中身を再確認できない**。設定ミス疑い時はワークフローで `len()` `head/tail` をログ出力して切り分け。
12. **重要操作時は sudo mode** が発動、メール認証が必要。

### Wind correction の substring バグ（ローカル版で発見・未移植）

13. `"強く" in wind_text` は `"やや強く"` にも誤マッチする。
    elif の順序を `非常に強 → やや強 → 強く → else` にするか、`wind_text.replace("やや強く","")` で除外してから判定する。
    現状のクラウド版 main.py にもこのバグが残っている（やや強の日に -10℃補正される）。

---

## 残課題・改善アイデア

### すぐできる改善

- [ ] **生成失敗時の通知**：失敗時に Slack/LINE/メール通知（前日WAV再生を防ぐ）
- [ ] **メタデータ同時出力**：`today.json` に生成時刻を入れ、MacroDroid側で当日チェック
- [ ] **温度サニティチェック**：気温が -10℃ 未満 / 50℃ 超なら警告（JMAパースバグ早期発見）
- [ ] **wind_correction substring バグ修正**（ローカル版から移植）

### 中長期改善

- [ ] **走行ハザード4種をローカル版から移植**（凍結・強風・濡れ路面・熱中症の3文目アドバイス）
- [ ] **モデルアップグレード検討**：gpt-4o-mini → gpt-4o or Llama-3.3-70B（品質次第）
- [ ] **MacroDroid マクロをエクスポートしてリポジトリに保管**（環境再構築時の備え）

### 完了済み

- [x] **クラウド版を GitHub Models で復活**（2026-05-16）
- [x] **ローカル版の自動実行を停止**（2026-05-16、ファイル・タスクは保持）

---

## ファイル構成

```
weather-gifu/
├ main.py                       # メインスクリプト（標準ライブラリのみ）
├ requirements.txt              # 空（追加依存なし）
├ .gitignore                    # *.wav, __pycache__, .env
├ .github/workflows/morning.yml # GitHub Actions（Enabled）
├ NOTES.md                      # このファイル
└ README.md
```

## 環境変数

| 名前 | 用途 | 必須 |
|---|---|---|
| `OUTPUT_PATH` | WAV保存先 | デフォルト `today.wav`、workflow から指定 |
| `GITHUB_TOKEN` | GitHub Models 認証 | **GitHub Actions が自動付与** |
| `CEREBRAS_API_KEY` | （旧）Cerebras 認証 | 現コードでは未使用、secret は残置 |
| `GROQ_API_KEY` | （旧）Groq 認証 | 未使用 |
