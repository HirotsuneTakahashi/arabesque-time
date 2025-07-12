# 出退勤管理システム

SlackのダイレクトメッセージとWebページを使用した出退勤管理システムです。

## 機能

- **Slack連携**: Slackボットに「出勤」「退勤」とメッセージを送信することで打刻
- **Web管理**: 出退勤記録の確認、編集、削除
- **管理者機能**: 全ユーザーの出退勤記録を一覧表示
- **Slack認証**: Slackアカウントでのログイン機能

## 技術スタック

- **バックエンド**: Python, Flask, Slack Bolt for Python
- **データベース**: SQLAlchemy, PostgreSQL (開発中はSQLite)
- **フロントエンド**: Jinja2, Bootstrap 5

## セットアップ

### 1. 必要なライブラリのインストール

```bash
pip install -r requirements.txt
```

### 2. Slackアプリの設定

1. [Slack API](https://api.slack.com/apps)でアプリを作成
2. **OAuth & Permissions**で以下のスコープを追加:
   - `chat:write`
   - `users:read`
   - `users:read.email`
   - `identity.basic`
   - `identity.email`
3. **Event Subscriptions**を有効化:
   - Request URL: `https://your-domain.com/slack/events`
   - Subscribe to bot events: `message.im`
4. **App Home**でメッセージタブを有効化

### 3. 環境変数の設定

`.env`ファイルを作成し、以下の値を設定:

```env
# Slack Configuration
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_CLIENT_ID=your-client-id
SLACK_CLIENT_SECRET=your-client-secret

# Database Configuration
DATABASE_URL=sqlite:///attendance.db

# Flask Configuration
SECRET_KEY=your-secret-key-here
FLASK_ENV=development

# Admin Configuration
ADMIN_USER_ID=your-admin-slack-user-id
```

### 4. データベースの初期化

```bash
flask init-db
```

### 5. アプリケーションの起動

```bash
python app.py
```

## 使用方法

### 出勤打刻

Slackボットに以下のメッセージを送信:
- `出勤`
- `おはよう`

### 退勤打刻

Slackボットに以下のメッセージを送信:
- `退勤`
- `おつかれ`

### Webページでの確認

1. `http://localhost:5000`にアクセス
2. Slackアカウントでログイン
3. 出退勤記録を確認・編集

### 管理者機能

環境変数`ADMIN_USER_ID`に設定されたSlackユーザーIDを持つユーザーは、`/admin`ページで全ユーザーの出退勤記録を確認できます。

## ファイル構成

```
/
├── app.py                 # Flaskアプリケーション本体
├── models.py              # SQLAlchemyのモデル定義
├── requirements.txt       # 必要なライブラリ一覧
├── .env                   # 環境変数設定ファイル
├── attendance.db          # SQLiteデータベース (自動生成)
├── templates/
│   ├── _base.html         # ベーステンプレート
│   ├── index.html         # メインページ
│   ├── admin.html         # 管理者ページ
│   └── login.html         # ログインページ
├── static/
│   └── style.css          # カスタムCSS
└── README.md              # このファイル
```

## API エンドポイント

- `GET /`: メインページ（ログイン後）
- `GET /login`: ログインページ
- `GET /callback`: Slack OAuth コールバック
- `GET /logout`: ログアウト
- `POST /attendance/update/<id>`: 出退勤記録の更新
- `DELETE /attendance/delete/<id>`: 出退勤記録の削除
- `GET /admin`: 管理者ページ
- `POST /slack/events`: Slack イベント処理

## セキュリティ注意事項

- `.env`ファイルは絶対に公開リポジトリにコミットしないでください
- 本番環境では適切な認証とHTTPS通信を使用してください
- データベースのバックアップを定期的に取得してください

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。
