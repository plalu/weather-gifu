# weather-gifu

岐阜市の天気とバイク通勤向けアドバイスを、毎朝音声で読み上げる自動化スクリプトです。

## 何をするか

GitHub Actions が毎朝自動で動き、気象庁データから岐阜市向けの天気情報を取得して、読み上げ用の `today.wav` を作成します。

作成した音声は GitHub Releases の `today` に上書きアップロードされます。

固定URL:

```text
https://github.com/plalu/weather-gifu/releases/download/today/today.wav
```

Android の MacroDroid などからこのURLを再生すると、毎朝の天気音声として使えます。

## 現在の構成

- 実行: GitHub Actions
- 実行時刻: 毎朝 04:45 / 05:00 / 05:15 / 05:45 / 06:15 JST
- 天気データ: 気象庁API
- 天気・風・降水確率: 美濃地方
- 気温予報: 岐阜地点
- 朝の体感温度: アメダス岐阜の観測気温を使用
- アドバイス生成: GitHub Models `openai/gpt-4o-mini`
- 音声生成: TTS Quest / VOICEVOX
- 話者: ずんだもん（ノーマル）
- 出力: `today.wav`

## 動作の流れ

1. 気象庁APIから岐阜県の予報を取得
2. 美濃地方の天気・風・降水確率を抽出
3. 岐阜地点の気温予報を抽出
4. アメダス岐阜の現在気温を取得
5. バイク通勤向けの体感温度と装備アドバイスを作成
6. VOICEVOX音声に変換
7. GitHub Releases の `today.wav` を更新

気象庁APIが一時的に `404` などを返した場合は、数回待って再試行します。
それでも天気データを取得できない場合は、古い天気を流さないため、失敗を知らせる音声で `today.wav` を上書きします。

## 手動実行

GitHub Actions の定期実行は混雑で大きく遅れることがあります。
7:30ごろの再生に間に合いやすくするため、早朝に複数回起動する設定にしています。

GitHub の Actions 画面から `morning-weather` を手動実行できます。

ローカルで試す場合:

```powershell
python main.py
```

標準では `today.wav` が作成されます。出力先を変えたい場合は `OUTPUT_PATH` を指定します。

```powershell
$env:OUTPUT_PATH="out.wav"
python main.py
```

## 環境変数

| 名前 | 用途 | 必須 |
| --- | --- | --- |
| `OUTPUT_PATH` | WAVの出力先 | いいえ |
| `GITHUB_TOKEN` | GitHub Models 認証 | GitHub Actionsでは自動 |
| `GOOGLE_TTS_API_KEY` | TTS Quest失敗時のGoogle TTS fallback | 任意 |
| `JMA_FRESHNESS_RETRIES` | 気象庁05:00発表待ちの再試行回数 | 任意 |
| `JMA_FRESHNESS_WAIT_SECONDS` | 再試行間隔 | 任意 |
| `JMA_HTTP_RETRIES` | 気象庁APIが一時不調のときの再試行回数 | 任意 |
| `JMA_HTTP_WAIT_SECONDS` | 気象庁API再試行の待ち時間 | 任意 |

## 注意

このリポジトリが Public の場合、Release にアップロードされた `today.wav` も外部からアクセスできます。

Private リポジトリにすると、認証なしの固定URLから `today.wav` を取得する運用は使えなくなる可能性が高いです。
Private 化する場合は、先に音声ファイルの配信方法を別途用意してください。
