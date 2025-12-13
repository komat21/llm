import os
import json
import re 
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, render_template, request as flask_request

# --- 1. アプリケーションの初期化 ---
app = Flask(__name__)

# --- 2. RSSフィードとカテゴリの定義 ---
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

TAGS_CACHE: dict[str, list[str]] = {}

# 🚀 【修正1】起動時にタグキャッシュをクリアする関数を追加
def clear_tag_cache():
    """アプリケーション起動時にタグキャッシュをクリアする。"""
    global TAGS_CACHE
    TAGS_CACHE = {}
    print("--- サーバー起動時にタグキャッシュをクリアしました ---")

# --- 3. 環境変数の読み込み ---
def get_gemini_api_key() -> str:
    """環境変数からAPIキーを取得し、存在しない場合はエラーではなくNoneを返す（APIエラー回避のため）。"""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return api_key

# --- 4. RSS取得ロジック ＆ クリーニング ---
def fetch_rss_items(feed_url: str, max_items: int = 20):
    """URLからRSSフィードを読み込み、記事アイテムをリストで返す。"""
    try:
        req = Request(feed_url, headers={"User-Agent": "Mozilla/5.0 NewsApp"})
        with urlopen(req, timeout=10) as resp:
            data = resp.read()
    except (URLError, HTTPError) as e:
        print(f"RSS Feed Error: {e}")
        return []

    root = ET.fromstring(data)
    channel = root.find("channel")
    items: list[dict] = []
    if channel is None:
        return items

    for item in channel.findall("item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        summary = (item.findtext("description") or "").strip()

        # 【RSSデータクリーニング】タイトルや概要に意図せず含まれる先頭の番号（例: "1."）を削除
        if len(title) > 2 and title[0].isdigit() and title[1] in ('.', ' '):
            title = title[title.find(title[1]) + 1:].strip()
        if len(summary) > 2 and summary[0].isdigit() and summary[1] in ('.', ' '):
            summary = summary[summary.find(summary[1]) + 1:].strip()
            
        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": (item.findtext("pubDate") or "").strip(),
                }
            )
    return items

# --- 5. Gemini タグ生成ロジック (バッチ処理) ---
def generate_tags_for_titles(items: list[dict]) -> None:
    """
    ニュースアイテムのリストからタイトルを抽出し、1回の Gemini 呼び出しでまとめてタグ生成する。
    """
    uncached_items = [it for it in items if it["title"] and it["title"] not in TAGS_CACHE]
    if not uncached_items:
        return

    uncached_titles = [it["title"] for it in uncached_items]

    # 🚀 【修正2】APIキーが見つからない場合、早期リターンする
    api_key = get_gemini_api_key()
    if not api_key:
        print("FATAL: Gemini API キーが見つかりません。タグ生成をスキップします。")
        # タグがないことを示すために、キャッシュに空リストをセット
        for title in uncached_titles:
             TAGS_CACHE[title] = []
        return

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
        f"?{urlencode({'key': api_key})}"
    )

    # プロンプトの構築
    lines: list[str] = []
    lines.append("次に示す複数のニュースタイトルごとに、その内容を要約する日本語タグを最大3個生成してください。")
    lines.append("出力は必ず、各行が「N: タグ1, タグ2, ...」という形式になるようにしてください。")
    lines.append("N はタイトルの番号です。タグ以外の説明文や余計な文章は書かないでください。")
    lines.append("")
    lines.append("タイトル一覧:")
    for idx, title in enumerate(uncached_titles, start=1):
        lines.append(f"{idx}. {title}")

    prompt = "\n".join(lines)

    # APIリクエストの実行
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Gemini API Call Error: {e}")
        # API呼び出しエラー時もタグがないことを示すために、キャッシュに空リストをセット
        for title in uncached_titles:
             TAGS_CACHE[title] = []
        return

    # レスポンスのパース
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        print("Gemini Response Parse Error: Invalid structure")
        # パースエラー時もタグがないことを示すために、キャッシュに空リストをセット
        for title in uncached_titles:
             TAGS_CACHE[title] = []
        return

    # 行ごとにパースし、キャッシュに保存
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if idx >= len(uncached_titles):
            break
        
        # "N: ..." の形式からタグ部分を抽出 (例: "1: タグ1, タグ2" -> "タグ1, タグ2")
        tags_part = line.split(":", 1)[-1].strip() if ":" in line else line.strip()

        # カンマまたは読点 (、) で分割
        raw_tags = [t.strip() for t in tags_part.replace("、", ",").split(",")]
        
        # 【タグクリーニング】タグ個別のクリーニング (先頭の番号を確実に削除)
        tags = []
        for t in raw_tags:
            t = t.strip()
            # タグの先頭に、プロンプトの番号が残っていた場合に対応 (例: "1.〇〇" -> "〇〇")
            if len(t) > 2 and t[0].isdigit() and t[1] in ('.', ' '):
                t = t[t.find(t[1]) + 1:].strip()
            
            # 不要な数字や短い句読点だけのタグを防ぐ
            if t and not t.isdigit() and len(t) > 1:
                tags.append(t)
        
        # 3個までに制限してキャッシュに保存
        TAGS_CACHE[uncached_titles[idx]] = tags[:3]


# --- 6. Flask ルーティング ---

@app.route('/')
def index():
    """メイン画面の表示"""
    return render_template('index.html', categories=CATEGORIES)

@app.route('/api/news/<category_name>', methods=['GET'])
def get_category_news(category_name):
    """カテゴリ名を受け取り、ニュースを取得し、JSONで返却するAPIエンドポイント。"""
    feed_url = CATEGORY_FEEDS_URLS.get(category_name)
    
    if not feed_url:
        return jsonify({"error": "指定されたカテゴリのRSSフィードが見つかりません"}), 404

    # 1. RSSからアイテムを取得
    items = fetch_rss_items(feed_url, max_items=20)
    
    if not items:
           return jsonify({"error": "ニュースの取得に失敗しました。フィードURLを確認してください。"}), 500

    # 🚀 【修正3】APIキーがない場合はエラーを返す
    if not get_gemini_api_key():
        # フロントエンドがエラーメッセージを表示できるように500エラーを返す
        return jsonify({"error": "Geminiクライアントが初期化されていません。環境変数 GEMINI_API_KEY を確認してください。"}), 500

    # 2. 先頭10件を対象に、Geminiでタグ生成
    target_items = items[:10]
    generate_tags_for_titles(target_items) 

    result_items = []
    for item in target_items:
        tags = TAGS_CACHE.get(item["title"], [])
        
        result_items.append({
            "title": item["title"],
            "summary": item.get("summary", "概要なし"), 
            "link": item["link"],
            "tags": tags
        })
    
    return jsonify({"news": result_items, "category": category_name})


# --- 7. サーバー起動 ---

if __name__ == '__main__':
    # サーバー起動直前にタグキャッシュをクリア
    clear_tag_cache()
    
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)