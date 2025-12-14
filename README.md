#ニュース分類アプリ

このアプリケーションは、Google NewsのRSSフィードから最新ニュースを取得し、Google Gemini APIを使用して各記事の主要なトピックを要約した日本語タグを自動生成して表示するWebアプリです。

---

## 機能概要

- Google News RSS からリアルタイムなニュースを取得
- 5 つのカテゴリを画面上で切り替え（政治 / 経済 / IT・科学 / 国際 / テクノロジー）
- 各ニュースごとに Gemini API で最大 3 個の日本語タグを自動生成
- Python + Flask のシンプルな構成

---

## 必要環境

- Python 3.10 以上推奨
- インターネット接続
- Google Gemini API キー（Google AI Studio または Google Cloud で取得）

---

## セットアップ手順

1. リポジトリをクローン（または展開）

   ```bash
   git clone <このリポジトリのURL>
   cd llm  # 実際のフォルダ名に合わせてください
   ```

2. Python パッケージのインストール

   （仮想環境を作成して使うことを推奨）

   ```bash
   pip install flask
   ```

3. ファイルの配置確認

   アプリケーションは、以下のファイル構造を前提としています。

   ```bash
    プロジェクトフォルダ/
    ├── app.py
    └── templates/
    └── index.html
   ```

---

## アプリの起動方法（APIキーのセットアップ）

  【重要】 本プロジェクトは、APIキーをファイルに書き込まず、ターミナルの環境変数として設定することを必須としています。
   プロジェクトのルートディレクトリで、APIキーを設定しつつ、続けてアプリケーションを実行します。

    
   ```bash
    環境	        実行コマンド
    Mac / Linux     export GEMINI_API_KEY="あなたのAPIキーをここに貼り付けます" && python app.py
    (Bash/Zsh)	
    Windows         $env:GEMINI_API_KEY="あなたのAPIキーをここに貼り付けます" ; python app.py
    (PowerShell)	
   ```
    
  - デフォルトではポート `5000` で起動します。
    
  - ブラウザで次の URL にアクセスしてください。

  - `http://localhost:5000/`

---

## 使い方

- 画面上部のカテゴリ選択ドロップダウンからカテゴリを選択すると、ニュースがそのカテゴリに切り替わります。
- 各ニュースには
  - タイトル（クリックで元記事へ）
  - 概要
  -Gemini が生成した日本語タグ（最大 3 個） が表示されます。
- ニュース取得およびタグ生成には数秒〜十数秒かかる場合があります（仕様上問題ない前提）。

---

## 補足・トラブルシューティング

- タグが表示されない場合
  - サーバーが起動しているターミナルに Gemini API Call Error または FATAL: Gemini API キーが見つかりません。 と出ていないか確認してください。
  - 起動コマンドで GEMINI_API_KEY が正しく設定されているか確認してください。
  - API キーが正しいサービス（Google AI Studio / Generative Language API）用のキーであることを確認してください。

- ポート番号を変更したい場合
  - app.py の最後付近にある app.run 実行前に、PORT 環境変数を設定して起動してください

    ```Bash
    # 例: ポート 8000 で起動
    export PORT=8000 && export GEMINI_API_KEY="キー" && python app.py
    ```
