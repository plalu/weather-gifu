import os
import sys
import time
import json
import datetime
import urllib.request
import urllib.parse

JMA_FORECAST = "https://www.jma.go.jp/bosai/forecast/data/forecast/210000.json"
JMA_OVERVIEW = "https://www.jma.go.jp/bosai/forecast/data/overview_forecast/210000.json"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TTS_QUEST_URL = "https://api.tts.quest/v3/voicevox/synthesis"
SPEAKER_ID = 8
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "today.wav")


def http_json(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


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
    weather_text = gifu_area["weathers"][0].replace("　", "")
    wind_text = gifu_area["winds"][0].replace("　", "")

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
            week = forecast[1]["timeSeries"]
            for s in week:
                for a in s.get("areas", []):
                    if "tempsMin" not in a and "tempsMax" not in a:
                        continue
                    for t, lo, hi in zip(s["timeDefines"], a.get("tempsMin", []), a.get("tempsMax", [])):
                        if not t.startswith(today_str):
                            continue
                        if temp_min is None and lo:
                            temp_min = int(lo)
                        if temp_max is None and hi:
                            temp_max = int(hi)
        except Exception:
            pass

    return {
        "summary": weather_text.split()[0] if weather_text else "不明",
        "overview_text": overview.get("text", "").replace("\n", "").replace("　", "").strip(),
        "weather_text": weather_text,
        "wind_text": wind_text,
        "temp_min": temp_min,
        "temp_max": temp_max,
        "pop_morning": pop_morning if pop_morning is not None else 0,
        "pop_noon": pop_noon if pop_noon is not None else 0,
        "pop_evening": pop_evening if pop_evening is not None else 0,
    }


def wind_correction(wind_text):
    if "非常に強" in wind_text:
        return -13
    if "強く" in wind_text:
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

    pop_max = max(w["pop_morning"], w["pop_evening"])
    if pop_max >= 50:
        rain = "降水確率が高いので、長靴とレインウェアを着用してください。"
    elif pop_max >= 30:
        rain = "念のためレインウェアを携帯してください。"
    else:
        rain = "雨具は不要です。"
    return gear + rain


def groq_advice(w, felt_temp, api_key):
    prompt = (
        "あなたは岐阜市でバイク通勤するライダー向けのアドバイザーです。"
        "以下の天気データから、80字以内の自然な日本語アドバイスを1文で生成してください。"
        "装備（グローブ・ジャケット・防寒）と雨具の要否に必ず触れてください。\n"
        f"最高気温:{w['temp_max']}度 最低気温:{w['temp_min']}度 "
        f"走行時体感温度:{felt_temp}度 "
        f"風:{w['wind_text']} "
        f"降水確率(朝):{w['pop_morning']}% (夕):{w['pop_evening']}%"
    )
    body = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 200,
    }).encode("utf-8")
    res = http_json(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=body,
        timeout=20,
    )
    return res["choices"][0]["message"]["content"].strip()


def build_advice(w):
    base_temp = w["temp_min"] if w["temp_min"] is not None else 10
    felt_temp = base_temp + wind_correction(w["wind_text"])

    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        try:
            advice = groq_advice(w, felt_temp, api_key)
            return felt_temp, advice
        except Exception as e:
            print(f"[warn] groq failed: {e}", file=sys.stderr)
    return felt_temp, rule_based_advice(w, felt_temp)


def build_message(w):
    today = datetime.date.today()
    felt_temp, advice = build_advice(w)
    high = f"{w['temp_max']}度" if w["temp_max"] is not None else "不明"
    low = f"{w['temp_min']}度" if w["temp_min"] is not None else "不明"
    morning_temp = w["temp_min"] if w["temp_min"] is not None else 10
    morning = f"{morning_temp}度" if w["temp_min"] is not None else "不明"
    pop_part = f"降水確率は朝{w['pop_morning']}パーセント、夕方{w['pop_evening']}パーセントです。"
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
    res = http_json(url, timeout=30)
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


def main():
    w = fetch_weather()
    print(f"[info] weather: {w['summary']} {w['temp_min']}/{w['temp_max']}", file=sys.stderr)
    msg = build_message(w)
    print(f"[info] message ({len(msg)} chars):\n{msg}", file=sys.stderr)
    synthesize(msg, OUTPUT_PATH)
    print(f"[info] wrote {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
