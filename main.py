import os
import sys
import time
import json
import base64
import datetime
import urllib.request
import urllib.parse
import urllib.error

JMA_FORECAST = "https://www.jma.go.jp/bosai/forecast/data/forecast/210000.json"
JMA_OVERVIEW = "https://www.jma.go.jp/bosai/forecast/data/overview_forecast/210000.json"
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODEL = "openai/gpt-4o-mini"
TTS_QUEST_URL = "https://api.tts.quest/v3/voicevox/synthesis"
SPEAKER_ID = 3  # ずんだもん（ノーマル）
GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
GOOGLE_TTS_VOICE = "ja-JP-Neural2-B"
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "today.wav")


def http_json(url, headers=None, data=None, timeout=30, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {}, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt >= retries:
                raise
            wait = 2 ** attempt
            print(
                f"[warn] http_json failed (attempt {attempt+1}/{retries+1}): {e}; retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)


def http_download(url, path, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "weather-gifu/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        f.write(r.read())


def fetch_weather():
    forecast = http_json(JMA_FORECAST, headers={"User-Agent": "weather-gifu/1.0"})
    overview = http_json(JMA_OVERVIEW, headers={"User-Agent": "weather-gifu/1.0"})

    today_block = forecast[0]
    ts = today_block["timeSeries"]

    gifu_area = next(
        (a for a in ts[0]["areas"] if a["area"]["name"] == "岐阜地方"),
        ts[0]["areas"][0],
    )
    # JMAの全角スペースは読点に置換すると読み上げが自然になる
    weather_text = gifu_area["weathers"][0].replace("　", "、").strip()
    wind_text = gifu_area["winds"][0].replace("　", "、").strip()

    pops_area = next(
        (a for a in ts[1]["areas"] if a["area"]["name"] == "岐阜地方"),
        ts[1]["areas"][0],
    )
    pop_defines = ts[1]["timeDefines"]
    pops = pops_area["pops"]
    today_str = datetime.date.today().isoformat()
    pop_morning = pop_noon = pop_evening = None
    for t, p in zip(pop_defines, pops):
        if not t.startswith(today_str):
            continue
        hour = int(t[11:13])
        if hour == 6:
            pop_morning = int(p) if p else None
        elif hour == 12:
            pop_noon = int(p) if p else None
        elif hour == 18:
            pop_evening = int(p) if p else None

    temp_min = temp_max = None
    for series in ts:
        for area in series.get("areas", []):
            if "temps" not in area:
                continue
            defines = series["timeDefines"]
            temps = area["temps"]
            for t, v in zip(defines, temps):
                if not v or not t.startswith(today_str):
                    continue
                hour = int(t[11:13])
                if hour < 9 and temp_min is None:
                    temp_min = int(v)
                elif hour >= 9 and temp_max is None:
                    temp_max = int(v)

    if temp_min is None or temp_max is None:
        try:
            for s in forecast[1]["timeSeries"]:
                defines = s.get("timeDefines", [])
                for a in s.get("areas", []):
                    tmins = a.get("tempsMin", [])
                    tmaxs = a.get("tempsMax", [])
                    for i, t in enumerate(defines):
                        if not t.startswith(today_str):
                            continue
                        if i < len(tmins) and tmins[i] and temp_min is None:
                            temp_min = int(tmins[i])
                        if i < len(tmaxs) and tmaxs[i] and temp_max is None:
                            temp_max = int(tmaxs[i])
        except Exception as e:
            print(f"[warn] week fallback failed: {e}", file=sys.stderr)

    print(f"[debug] temp_min={temp_min}, temp_max={temp_max}", file=sys.stderr)
    if pop_morning is None:
        print("[warn] pop_morning missing from JMA data", file=sys.stderr)
    if pop_evening is None:
        print("[warn] pop_evening missing from JMA data", file=sys.stderr)

    return {
        "summary": weather_text.split()[0] if weather_text else "不明",
        "overview_text": overview.get("text", "").replace("\n", "").replace("　", "").strip(),
        "weather_text": weather_text,
        "wind_text": wind_text,
        "temp_min": temp_min,
        "temp_max": temp_max,
        # データが取れない場合はNoneのまま下流に渡し、表示側で「不明」として扱う
        "pop_morning": pop_morning,
        "pop_noon": pop_noon,
        "pop_evening": pop_evening,
    }


def wind_correction(wind_text):
    # 「やや強」が「強く」のsubstringにマッチしないよう除外してから判定
    without_yaya = wind_text.replace("やや強", "") if wind_text else ""
    if "非常に強" in wind_text:
        return -13
    if "強く" in without_yaya:
        return -10
    if "やや強" in wind_text:
        return -7
    return -5


def rule_based_advice(w, felt_temp):
    if felt_temp < 5:
        gear = "電熱グローブと防寒インナーをしっかり装備してください。"
    elif felt_temp < 10:
        gear = "厚手グローブと防寒インナーが必要です。"
    elif felt_temp < 15:
        gear = "春秋用グローブにインナー1枚で大丈夫です。"
    else:
        gear = "メッシュジャケットと薄手グローブで快適に走れます。"

    known_pops = [p for p in (w["pop_morning"], w["pop_evening"]) if p is not None]
    if not known_pops:
        rain = "降水確率データが取得できないため、念のためレインウェアを携帯してください。"
    else:
        pop_max = max(known_pops)
        if pop_max >= 50:
            rain = "降水確率が高いので、長靴とレインウェアを着用してください。"
        elif pop_max >= 30:
            rain = "念のためレインウェアを携帯してください。"
        else:
            rain = "雨具は不要です。"
    return gear + rain


def github_models_advice(w, felt_temp, token):
    pm = f"{w['pop_morning']}%" if w["pop_morning"] is not None else "不明"
    pe = f"{w['pop_evening']}%" if w["pop_evening"] is not None else "不明"
    prompt = (
        "あなたは岐阜市でバイク通勤するライダー向けのアドバイザーです。"
        "以下の天気データから、80字以内の自然な日本語アドバイスを1文で生成してください。"
        "装備（グローブ・ジャケット・防寒）と雨具の要否に必ず触れてください。\n"
        f"最高気温:{w['temp_max']}度 最低気温:{w['temp_min']}度 "
        f"走行時体感温度:{felt_temp}度 "
        f"風:{w['wind_text']} "
        f"降水確率(朝):{pm} (夕):{pe}"
    )
    body = json.dumps({
        "model": GITHUB_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 200,
    }).encode("utf-8")
    res = http_json(
        GITHUB_MODELS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=body,
        timeout=30,
    )
    return res["choices"][0]["message"]["content"].strip()


def build_advice(w):
    base_temp = w["temp_min"] if w["temp_min"] is not None else 10
    felt_temp = base_temp + wind_correction(w["wind_text"])

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            advice = github_models_advice(w, felt_temp, token)
            return felt_temp, advice
        except Exception as e:
            print(f"[warn] github models failed: {e}", file=sys.stderr)
    return felt_temp, rule_based_advice(w, felt_temp)


def build_message(w):
    today = datetime.date.today()
    felt_temp, advice = build_advice(w)
    high = f"{w['temp_max']}度" if w["temp_max"] is not None else "不明"
    low = f"{w['temp_min']}度" if w["temp_min"] is not None else "不明"
    morning_temp = w["temp_min"] if w["temp_min"] is not None else 10
    morning = f"{morning_temp}度" if w["temp_min"] is not None else "不明"
    pm = f"{w['pop_morning']}パーセント" if w["pop_morning"] is not None else "不明"
    pe = f"{w['pop_evening']}パーセント" if w["pop_evening"] is not None else "不明"
    pop_part = f"降水確率は朝{pm}、夕方{pe}です。"
    return (
        f"おはようございます。{today.month}月{today.day}日の岐阜市の天気をお伝えします。"
        f"天気は{w['weather_text']}です。"
        f"最高気温は{high}、最低気温は{low}の見込みです。"
        f"風は{w['wind_text']}の予報です。"
        f"{pop_part}"
        f"バイク通勤アドバイスです。"
        f"朝の気温は{morning}ですが、走行風で体感温度は{felt_temp}度前後になります。"
        f"{advice}"
        f"本日も安全運転でいってらっしゃい。"
    )


def synthesize(text, out_path):
    params = urllib.parse.urlencode({"speaker": SPEAKER_ID, "text": text})
    url = f"{TTS_QUEST_URL}?{params}"
    res = http_json(url, timeout=60, retries=3)
    if not res.get("success"):
        raise RuntimeError(f"TTS Quest rejected request: {res}")

    status_url = res.get("audioStatusUrl")
    wav_url = res.get("wavDownloadUrl")
    if not status_url or not wav_url:
        raise RuntimeError(f"TTS Quest unexpected response: {res}")

    print("[info] waiting for TTS Quest synthesis...", file=sys.stderr)
    for i in range(90):
        status = http_json(status_url, timeout=15)
        if status.get("isAudioError"):
            raise RuntimeError(f"TTS Quest synthesis error: {status}")
        if status.get("isAudioReady"):
            print(f"[info] synthesis ready after {i*2}s", file=sys.stderr)
            break
        if i % 5 == 0:
            print(f"[info]   ...still waiting ({i*2}s elapsed)", file=sys.stderr)
        time.sleep(2)
    else:
        raise RuntimeError("TTS Quest synthesis timed out (180s)")

    print("[info] downloading WAV...", file=sys.stderr)
    http_download(wav_url, out_path)
    with open(out_path, "rb") as f:
        head = f.read(4)
    if head != b"RIFF":
        raise RuntimeError("Downloaded file is not a WAV (got: %r)" % head)


def synthesize_google_tts(text, out_path, api_key):
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": "ja-JP", "name": GOOGLE_TTS_VOICE},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000},
    }).encode("utf-8")
    url = f"{GOOGLE_TTS_URL}?key={urllib.parse.quote(api_key)}"
    res = http_json(
        url,
        headers={"Content-Type": "application/json"},
        data=body,
        timeout=60,
        retries=2,
    )
    audio = res.get("audioContent")
    if not audio:
        raise RuntimeError(f"Google TTS missing audioContent: {res}")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(audio))
    with open(out_path, "rb") as f:
        head = f.read(4)
    if head != b"RIFF":
        raise RuntimeError("Google TTS output is not a WAV (got: %r)" % head)


def synthesize_with_fallback(text, out_path):
    try:
        synthesize(text, out_path)
        return "tts-quest"
    except Exception as e:
        print(f"[warn] TTS Quest failed: {e}", file=sys.stderr)
        api_key = os.environ.get("GOOGLE_TTS_API_KEY")
        if not api_key:
            print("[error] GOOGLE_TTS_API_KEY not set; no fallback available", file=sys.stderr)
            raise
        print("[info] falling back to Google Cloud TTS", file=sys.stderr)
        synthesize_google_tts(text, out_path, api_key)
        return "google-tts"


def main():
    w = fetch_weather()
    print(f"[info] weather: {w['summary']} {w['temp_min']}/{w['temp_max']}", file=sys.stderr)
    msg = build_message(w)
    print(f"[info] message ({len(msg)} chars):\n{msg}", file=sys.stderr)
    backend = synthesize_with_fallback(msg, OUTPUT_PATH)
    print(f"[info] wrote {OUTPUT_PATH} via {backend}", file=sys.stderr)


if __name__ == "__main__":
    main()
