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
# 3. タグキャッシュ
#   ★ title → link に変更
# ==============================
TAGS_CACHE: dict[str, list[str]] = {}

# ==============================
# 4. 共通ユーティリティ
# ==============================
def get_gemini_api_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def clean_leading_number(text: str) -> str:
    """先頭の番号・記号を除去"""
    if not text:
        return ""
    return re.sub(r"^[\d０-９①-⑳]+[\.．、)\s]+", "", text).strip()


def is_valid_tag(tag: str) -> bool:
    """タグとして有効か判定"""
    if not tag:
        return False
    # 数字・記号だけは除外
    if re.fullmatch(r"[\d０-９①-⑳\.\．、\(\)\s]+", tag):
        return False
    return True

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
        title = clean_leading_number(item.findtext("title") or "")
        summary = clean_leading_number(item.findtext("description") or "")
        link = item.findtext("link") or ""

        if title and link:
            items.append({
                "title": title.strip(),
                "summary": summary.strip(),
                "link": link.strip(),
            })
    return items

# ==============================
# 6. Gemini タグ生成
#   ★ キャッシュキーは link
# ==============================
def generate_tags_for_items(items: list[dict]) -> None:
    uncached = [it for it in items if it["link"] not in TAGS_CACHE]
    if not uncached:
        return

    api_key = get_gemini_api_key()
    if not api_key:
        for it in uncached:
            TAGS_CACHE[it["link"]] = []
        return

    titles = [it["title"] for it in uncached]
    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?{urlencode({'key': api_key})}"
    )

    prompt = (
        "以下のニュースタイトルそれぞれについて、日本語タグを最大3個生成してください。\n"
        "番号や記号は一切含めず、カンマ区切りのタグのみを出力してください。\n\n"
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
        for it in uncached:
            TAGS_CACHE[it["link"]] = []
        return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for item, line in zip(uncached, lines):
        raw_tags = [
            clean_leading_number(t.strip())
            for t in line.replace("、", ",").split(",")
        ]
        tags = [t for t in raw_tags if is_valid_tag(t)]
        TAGS_CACHE[item["link"]] = tags[:3]

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
        return jsonify({"error": "invalid category"}), 404

    items = fetch_rss_items(feed_url)
    if not items:
        return jsonify({"error": "no news"}), 500

    target = items[:10]
    generate_tags_for_items(target)

    return jsonify({
        "news": [
            {
                "title": it["title"],
                "summary": it["summary"],
                "link": it["link"],
                "tags": TAGS_CACHE.get(it["link"], [])
            }
            for it in target
        ]
    })

# ==============================
# 8. 起動
# ==============================
if __name__ == "__main__":
    TAGS_CACHE.clear()
    app.run(host="0.0.0.0", port=5000, debug=False)
