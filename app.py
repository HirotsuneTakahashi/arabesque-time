import os
import re
from datetime import datetime, timezone
from flask import Flask, render_template, redirect, url_for, request, jsonify, session, flash
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from models import db, User, Attendance
from dotenv import load_dotenv
import threading
import requests
import logging

# ログ設定の改善
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数を読み込み
load_dotenv()

# 必須環境変数の検証
required_env_vars = [
    'SLACK_BOT_TOKEN',
    'SLACK_SIGNING_SECRET',
    'SLACK_CLIENT_ID',
    'SLACK_CLIENT_SECRET'
]

missing_vars = []
for var in required_env_vars:
    if not os.environ.get(var):
        missing_vars.append(var)

if missing_vars:
    logger.error(f"Missing required environment variables: {missing_vars}")
    raise ValueError(f"Missing required environment variables: {missing_vars}")

# Flaskアプリケーションの設定
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key-for-development')

# データベース設定の改善
database_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
# PostgreSQL URL の修正（ssl require対応）
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_timeout': 20,
    'pool_recycle': -1,
    'pool_pre_ping': True
}

# データベースの初期化
db.init_app(app)

# Slack Boltアプリケーションの設定（最適化）
slack_app = App(
    token=os.environ.get('SLACK_BOT_TOKEN'),
    signing_secret=os.environ.get('SLACK_SIGNING_SECRET'),
    process_before_response=True
)

# Slack Web クライアント
slack_client = WebClient(token=os.environ.get('SLACK_BOT_TOKEN'))

# SlackRequestHandlerの設定
handler = SlackRequestHandler(slack_app)

# Slack Bot イベントリスナー（最適化）
@slack_app.message(re.compile(r'(出勤|おはよう)', re.IGNORECASE))
def handle_checkin(message, say):
    """出勤打刻を処理"""
    try:
        user_id = message['user']
        logger.info(f"Received checkin message from user: {user_id}")
        
        # ユーザー情報を取得
        user = get_or_create_user(user_id)
        if not user:
            logger.error(f"Failed to get or create user: {user_id}")
            say("申し訳ありませんが、ユーザー情報の取得に失敗しました。")
            return
        
        # 出勤記録を作成
        attendance = Attendance(
            user_id=user.id,
            type='出勤',
            timestamp=datetime.now(timezone.utc)
        )
        
        db.session.add(attendance)
        db.session.commit()
        
        # 返信メッセージを送信
        say(f"出勤打刻を受け付けました！ {attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Checkin recorded for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling checkin: {e}")
        say("申し訳ありませんが、出勤打刻の処理中にエラーが発生しました。")

@slack_app.message(re.compile(r'(退勤|おつかれ)', re.IGNORECASE))
def handle_checkout(message, say):
    """退勤打刻を処理"""
    try:
        user_id = message['user']
        logger.info(f"Received checkout message from user: {user_id}")
        
        # ユーザー情報を取得
        user = get_or_create_user(user_id)
        if not user:
            logger.error(f"Failed to get or create user: {user_id}")
            say("申し訳ありませんが、ユーザー情報の取得に失敗しました。")
            return
        
        # 退勤記録を作成
        attendance = Attendance(
            user_id=user.id,
            type='退勤',
            timestamp=datetime.now(timezone.utc)
        )
        
        db.session.add(attendance)
        db.session.commit()
        
        # 返信メッセージを送信
        say(f"退勤打刻を受け付けました！ {attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Checkout recorded for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling checkout: {e}")
        say("申し訳ありませんが、退勤打刻の処理中にエラーが発生しました。")

@slack_app.message(re.compile(r'(ヘルプ|help)', re.IGNORECASE))
def handle_help(message, say):
    """ヘルプメッセージを送信"""
    help_text = """
📋 **出退勤管理ボットの使い方**

🌅 **出勤打刻:**
• `出勤`
• `おはよう`

🌙 **退勤打刻:**
• `退勤`
• `おつかれ`

❓ **このヘルプを表示:**
• `ヘルプ`
• `help`

💻 **Web画面でも確認できます:**
アプリにログインして詳細な記録を確認できます。
    """
    say(help_text)

# デバッグ用メッセージハンドラーを削除（本番環境では不要）
# 代わりにapp_mentionsイベントのみ処理
@slack_app.event("app_mention")
def handle_app_mention(event, say):
    """ボットへのメンションを処理"""
    text = event.get('text', '').lower()
    if any(keyword in text for keyword in ['ヘルプ', 'help']):
        handle_help(event, say)
    else:
        say("こんにちは！出退勤管理ボットです。`ヘルプ`と送信すると使い方を確認できます。")

def get_or_create_user(slack_user_id):
    """Slackユーザー情報を取得または作成（エラーハンドリング改善）"""
    try:
        user = User.query.filter_by(slack_user_id=slack_user_id).first()
        
        if not user:
            try:
                # Slack APIからユーザー情報を取得
                response = slack_client.users_info(user=slack_user_id)
                if not response.get('ok'):
                    logger.error(f"Slack API error: {response.get('error')}")
                    return None
                    
                user_info = response['user']
                
                user = User(
                    slack_user_id=slack_user_id,
                    display_name=user_info.get('real_name', user_info.get('name', 'Unknown')),
                    email=user_info.get('profile', {}).get('email', '')
                )
                
                db.session.add(user)
                db.session.commit()
                logger.info(f"Created new user: {slack_user_id}")
                
            except SlackApiError as e:
                logger.error(f"Error fetching user info: {e}")
                # エラーの場合はデフォルトユーザーを作成
                user = User(
                    slack_user_id=slack_user_id,
                    display_name=f'User_{slack_user_id[-4:]}',  # IDの末尾4桁のみ表示
                    email=''
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"Created default user: {slack_user_id}")
            except Exception as e:
                logger.error(f"Database error creating user: {e}")
                return None
        
        return user
        
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return None

# Webアプリケーションのルート
@app.route('/')
def index():
    """ログイン後の出退勤一覧ページ"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            return redirect(url_for('login'))
        
        # ユーザーの出退勤記録を取得（最新順）
        attendances = Attendance.query.filter_by(user_id=user.id).order_by(Attendance.timestamp.desc()).all()
        
        return render_template('index.html', user=user, attendances=attendances)
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        flash('データの取得中にエラーが発生しました。', 'error')
        return redirect(url_for('login'))

@app.route('/', methods=['POST'])
def handle_slack_events():
    """Slackイベントを処理（ルートパス）"""
    return handler.handle(request)

@app.route('/login')
def login():
    """Slack認証ページ（スコープ修正）"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    # Slack OAuthのURL（適切なスコープに修正）
    client_id = os.environ.get('SLACK_CLIENT_ID')
    # OAuth用のUser Token Scopesは identity.basic のみ
    scope = 'identity.basic'
    redirect_uri = url_for('callback', _external=True)
    
    slack_oauth_url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}"
    
    return render_template('login.html', oauth_url=slack_oauth_url)

@app.route('/callback')
def callback():
    """Slack認証後のコールバック（エラーハンドリング改善）"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        logger.error(f"OAuth error: {error}")
        flash(f'認証エラー: {error}', 'error')
        return redirect(url_for('login'))
    
    if not code:
        logger.error("No authorization code received")
        flash('認証に失敗しました。認証コードが取得できませんでした。', 'error')
        return redirect(url_for('login'))
    
    try:
        # OAuth認証のトークン取得
        response = requests.post('https://slack.com/api/oauth.v2.access', {
            'client_id': os.environ.get('SLACK_CLIENT_ID'),
            'client_secret': os.environ.get('SLACK_CLIENT_SECRET'),
            'code': code,
            'redirect_uri': url_for('callback', _external=True)
        }, timeout=10)
        
        auth_data = response.json()
        logger.info(f"OAuth response: {auth_data}")  # デバッグ用ログ
        
        if not auth_data.get('ok'):
            error_msg = auth_data.get('error', 'Unknown error')
            logger.error(f"OAuth token exchange failed: {error_msg}")
            flash(f'認証に失敗しました: {error_msg}', 'error')
            return redirect(url_for('login'))
        
        # ユーザー情報取得
        user_token = auth_data['authed_user']['access_token']
        user_info_response = requests.get(
            'https://slack.com/api/users.identity',
            headers={'Authorization': f'Bearer {user_token}'},
            timeout=10
        )
        
        user_info = user_info_response.json()
        logger.info(f"User info response: {user_info}")  # デバッグ用ログ
        
        if not user_info.get('ok'):
            error_msg = user_info.get('error', 'Unknown error')
            logger.error(f"User info fetch failed: {error_msg}")
            flash(f'ユーザー情報の取得に失敗しました: {error_msg}', 'error')
            return redirect(url_for('login'))
        
        slack_user_id = user_info['user']['id']
        
        # ユーザーを取得または作成
        user = User.query.filter_by(slack_user_id=slack_user_id).first()
        
        if not user:
            user = User(
                slack_user_id=slack_user_id,
                display_name=user_info['user']['name'],
                email=''  # identity.basicスコープではメールアドレスは取得できない
            )
            db.session.add(user)
            db.session.commit()
            logger.info(f"Created new user via OAuth: {slack_user_id}")
        
        # セッションに保存
        session['user_id'] = user.id
        session['slack_user_id'] = slack_user_id
        
        flash('ログインしました。', 'success')
        return redirect(url_for('index'))
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during OAuth: {e}")
        flash('ネットワークエラーが発生しました。しばらく待ってから再試行してください。', 'error')
        return redirect(url_for('login'))
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        flash('認証処理中にエラーが発生しました。', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    """ログアウト処理"""
    session.clear()
    flash('ログアウトしました。', 'info')
    return redirect(url_for('login'))

@app.route('/attendance/update/<int:id>', methods=['POST'])
def update_attendance(id):
    """出退勤記録の更新"""
    if 'user_id' not in session:
        return jsonify({'error': 'ログインが必要です'}), 401
    
    try:
        attendance = Attendance.query.get(id)
        if not attendance:
            return jsonify({'error': '記録が見つかりません'}), 404
        
        # 所有者チェック
        if attendance.user_id != session['user_id']:
            return jsonify({'error': '権限がありません'}), 403
        
        data = request.get_json()
        
        if 'type' in data:
            attendance.type = data['type']
        
        if 'timestamp' in data:
            try:
                attendance.timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
            except ValueError:
                return jsonify({'error': '日時の形式が正しくありません'}), 400
        
        attendance.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        
        return jsonify({'message': '更新しました', 'attendance': attendance.to_dict()})
    except Exception as e:
        logger.error(f"Error updating attendance: {e}")
        return jsonify({'error': '更新中にエラーが発生しました'}), 500

@app.route('/attendance/delete/<int:id>', methods=['DELETE'])
def delete_attendance(id):
    """出退勤記録の削除"""
    if 'user_id' not in session:
        return jsonify({'error': 'ログインが必要です'}), 401
    
    try:
        attendance = Attendance.query.get(id)
        if not attendance:
            return jsonify({'error': '記録が見つかりません'}), 404
        
        # 所有者チェック
        if attendance.user_id != session['user_id']:
            return jsonify({'error': '権限がありません'}), 403
        
        db.session.delete(attendance)
        db.session.commit()
        
        return jsonify({'message': '削除しました'})
    except Exception as e:
        logger.error(f"Error deleting attendance: {e}")
        return jsonify({'error': '削除中にエラーが発生しました'}), 500

@app.route('/admin')
def admin():
    """管理者用の全ユーザー出退勤一覧ページ"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        # 管理者チェック
        user = User.query.get(session['user_id'])
        admin_user_id = os.environ.get('ADMIN_USER_ID')
        
        if not user or user.slack_user_id != admin_user_id:
            flash('管理者権限が必要です。', 'error')
            return redirect(url_for('index'))
        
        # 全ユーザーの出退勤記録を取得
        attendances = db.session.query(Attendance, User).join(User).order_by(Attendance.timestamp.desc()).all()
        
        return render_template('admin.html', attendances=attendances)
    except Exception as e:
        logger.error(f"Error in admin route: {e}")
        flash('データの取得中にエラーが発生しました。', 'error')
        return redirect(url_for('index'))

# Slack イベントエンドポイント
@app.route('/slack/events', methods=['POST'])
def slack_events():
    """Slack イベントを処理"""
    return handler.handle(request)

# ヘルスチェックエンドポイント（デプロイ最適化）
@app.route('/health')
def health_check():
    """ヘルスチェックエンドポイント"""
    try:
        # データベース接続確認
        db.session.execute('SELECT 1')
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503

# データベース初期化コマンド
@app.cli.command()
def init_db():
    """データベースを初期化"""
    try:
        db.create_all()
        logger.info('データベースが初期化されました。')
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

# アプリケーション初期化関数
def create_app():
    """アプリケーションファクトリー関数"""
    try:
        with app.app_context():
            # データベーステーブルの作成（存在しない場合のみ）
            db.create_all()
            logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # データベース接続エラーでもアプリケーションは起動を続行
        pass
    
    return app

# Gunicorn用の初期化（本番環境）
if __name__ != '__main__':
    # Gunicornから起動される場合
    create_app()

if __name__ == '__main__':
    # 開発環境での直接実行
    try:
        # データベースの初期化
        with app.app_context():
            db.create_all()
            logger.info("Development server: Database initialized")
        
        # Flaskアプリケーションの起動
        app.run(debug=True, host='0.0.0.0', port=5001)
    except Exception as e:
        logger.error(f"Failed to start development server: {e}")
        raise 