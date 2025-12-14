import os
import json
import re
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, render_template

# ==============================
# 1. アプリ初期化
# ==============================
app = Flask(__name__)

# ==============================
# 2. RSS設定
# ==============================
GOOGLE_NEWS_BASE = "https://news.google.com/rss"

CATEGORY_FEEDS_URLS = {
    "政治": f"{GOOGLE_NEWS_BASE}/headlines/section/topic/POLITICS?hl=ja&gl=JP&ceid=JP:ja",
    "経済": f"{GOOGLE_NEWS_BASE}/headlines/section/topic/BUSINESS?hl=ja&gl=JP&ceid=JP:ja",
    "IT・科学": f"{GOOGLE_NEWS_BASE}/headlines/section/topic/SCIENCE?hl=ja&gl=JP&ceid=JP:ja",
    "国際": f"{GOOGLE_NEWS_BASE}/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja",
    "テクノロジー": f"{GOOGLE_NEWS_BASE}/headlines/section/topic/TECHNOLOGY?hl=ja&gl=JP&ceid=JP:ja",
}

CATEGORIES = list(CATEGORY_FEEDS_URLS.keys())
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# ==============================
# 3. キャッシュ（起動時に必ずクリア）
# ==============================
TAGS_CACHE: dict[str, list[str]] = {}

# ==============================
# 4. ユーティリティ
# ==============================
def get_gemini_api_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

def clean_leading_number(text: str) -> str:
    """
    先頭の番号・記号を完全除去
    例:
    1. xxx
    1) xxx
    ① xxx
    １．xxx
    """
    if not text:
        return ""
    return re.sub(r"^[\d０-９①-⑳]+[\.．、)\s]+", "", text).strip()

# ==============================
# 5. RSS取得
# ==============================
def fetch_rss_items(feed_url: str, max_items: int = 20):
    try:
        req = Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            data = resp.read()
    except (URLError, HTTPError) as e:
        print("RSS ERROR:", e)
        return []

    root = ET.fromstring(data)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item")[:max_items]:
        title = clean_leading_number((item.findtext("title") or "").strip())
        summary = clean_leading_number((item.findtext("description") or "").strip())
        link = (item.findtext("link") or "").strip()

        if title and link:
            items.append({
                "title": title,
                "summary": summary,
                "link": link
            })
    return items

# ==============================
# 6. Gemini タグ生成（番号完全禁止）
# ==============================
def generate_tags_for_titles(items: list[dict]) -> None:
    uncached = [it for it in items if it["title"] not in TAGS_CACHE]
    if not uncached:
        return

    api_key = get_gemini_api_key()
    if not api_key:
        for it in uncached:
            TAGS_CACHE[it["title"]] = []
        return

    titles = [it["title"] for it in uncached]
    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?{urlencode({'key': api_key})}"
    )

    # 🚫 番号・記号を一切使わせないプロンプト
    prompt = (
        "以下のニュースタイトルそれぞれについて、日本語タグを最大3個生成してください。\n"
        "出力は1行ごとに「タグ1, タグ2, タグ3」の形式のみ。\n"
        "番号、記号、箇条書き、説明文は一切含めないでください。\n\n"
        + "\n".join(titles)
    )

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print("GEMINI ERROR:", e)
        for t in titles:
            TAGS_CACHE[t] = []
        return

    # デバッグ用（必要なら有効化）
    # print("=== GEMINI RAW ===")
    # print(text)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for title, line in zip(titles, lines):
        tags = [
            clean_leading_number(t.strip())
            for t in line.replace("、", ",").split(",")
            if t.strip()
        ]
        TAGS_CACHE[title] = tags[:3]

# ==============================
# 7. ルーティング
# ==============================
@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)

@app.route("/api/news/<category>")
def get_news(category):
    feed_url = CATEGORY_FEEDS_URLS.get(category)
    if not feed_url:
        return jsonify({"error": "カテゴリ不正"}), 404

    items = fetch_rss_items(feed_url)
    if not items:
        return jsonify({"error": "ニュース取得失敗"}), 500

    target = items[:10]
    generate_tags_for_titles(target)

    result = []
    for it in target:
        result.append({
            "title": it["title"],
            "summary": it["summary"][:150],
            "link": it["link"],
            "tags": TAGS_CACHE.get(it["title"], [])
        })

    return jsonify({"news": result})

# ==============================
# 8. 起動
# ==============================
if __name__ == "__main__":
    TAGS_CACHE.clear()
    print("=== TAG CACHE CLEARED ===")
    app.run(host="0.0.0.0", port=5000, debug=False)
