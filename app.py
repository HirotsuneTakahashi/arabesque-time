import os
import re
from datetime import datetime, timezone, timedelta
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
import statistics
from collections import defaultdict

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

# セッション設定（持続性を改善）
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # セッションを30日間保持
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'  # 本番環境でのみHTTPS必須
app.config['SESSION_COOKIE_HTTPONLY'] = True  # JavaScriptからアクセス不可
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF保護

# データベース設定の改善
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # PostgreSQL用の接続設定の最適化
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,  # 接続前にping
        'pool_recycle': 3600,   # 1時間で接続をリサイクル
        'pool_size': 10,        # 接続プールサイズ
        'max_overflow': 20,     # 最大オーバーフロー
        'pool_timeout': 30,     # 接続タイムアウト（秒）
        'connect_args': {'sslmode': 'require', 'connect_timeout': 30}
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/attendance.db'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'pool_timeout': 30
    }

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# データベースの初期化
db.init_app(app)

# Slack Bolt の自動OAuth設定を無効にするために環境変数を一時的に削除
slack_client_id = os.environ.get('SLACK_CLIENT_ID')
slack_client_secret = os.environ.get('SLACK_CLIENT_SECRET')
if 'SLACK_CLIENT_ID' in os.environ:
    del os.environ['SLACK_CLIENT_ID']
if 'SLACK_CLIENT_SECRET' in os.environ:
    del os.environ['SLACK_CLIENT_SECRET']

# Slack Boltアプリケーションの設定（シンプルなトークンベース）
slack_app = App(
    token=os.environ.get('SLACK_BOT_TOKEN'),
    signing_secret=os.environ.get('SLACK_SIGNING_SECRET'),
    process_before_response=True
)

# 環境変数を復元
if slack_client_id:
    os.environ['SLACK_CLIENT_ID'] = slack_client_id
if slack_client_secret:
    os.environ['SLACK_CLIENT_SECRET'] = slack_client_secret

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
            except Exception as e:
                logger.error(f"Database error creating user: {e}")
                return None
        
        return user
        
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        return None

def calculate_work_hours_statistics(user_id=None):
    """活動時間の統計を計算（週単位）- 最適化版"""
    try:
        # 対象のユーザーを決定（最適化：必要なデータのみ取得）
        if user_id:
            attendances = Attendance.query.filter_by(user_id=user_id).order_by(Attendance.timestamp).all()
        else:
            # 全体統計の場合、過去3ヶ月に制限（パフォーマンス対策）
            three_months_ago = datetime.now(timezone.utc) - timedelta(days=90)
            attendances = Attendance.query.filter(
                Attendance.timestamp >= three_months_ago
            ).order_by(Attendance.timestamp).all()
        
        if not attendances:
            return {
                'weekly_hours': [],
                'average_hours': 0,
                'median_hours': 0,
                'total_weeks': 0,
                'total_hours': 0
            }
        
        # ユーザーごとの出退勤記録を整理
        user_attendances = defaultdict(list)
        for attendance in attendances:
            user_attendances[attendance.user_id].append(attendance)
        
        # 週ごとの作業時間を計算
        weekly_hours = []
        
        for uid, records in user_attendances.items():
            # 週ごとに記録を分類
            weekly_records = defaultdict(list)
            for record in records:
                week_start = record.timestamp.date() - timedelta(days=record.timestamp.weekday())
                weekly_records[week_start].append(record)
            
            # 各週の作業時間を計算（最適化：並列処理準備）
            for week_start, week_records in weekly_records.items():
                # 出勤と退勤をペアにして作業時間を計算
                checkin_records = [r for r in week_records if r.type == '出勤']
                checkout_records = [r for r in week_records if r.type == '退勤']
                
                week_hours = 0
                for checkin in checkin_records:
                    # 同じ日で最も近い退勤記録を探す
                    same_day_checkouts = [
                        c for c in checkout_records 
                        if c.timestamp.date() == checkin.timestamp.date() and c.timestamp > checkin.timestamp
                    ]
                    if same_day_checkouts:
                        checkout = min(same_day_checkouts, key=lambda x: x.timestamp)
                        hours = (checkout.timestamp - checkin.timestamp).total_seconds() / 3600
                        week_hours += hours
                
                if week_hours > 0:
                    weekly_hours.append(week_hours)
        
        # 統計値を計算
        if weekly_hours:
            average_hours = statistics.mean(weekly_hours)
            median_hours = statistics.median(weekly_hours)
            total_hours = sum(weekly_hours)
        else:
            average_hours = 0
            median_hours = 0
            total_hours = 0
        
        return {
            'weekly_hours': weekly_hours,
            'average_hours': round(average_hours, 2),
            'median_hours': round(median_hours, 2),
            'total_weeks': len(weekly_hours),
            'total_hours': round(total_hours, 2)
        }
        
    except Exception as e:
        logger.error(f"Error calculating statistics: {e}")
        return {
            'weekly_hours': [],
            'average_hours': 0,
            'median_hours': 0,
            'total_weeks': 0,
            'total_hours': 0
        }

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
        
        # 管理者権限チェック用
        admin_user_id = os.environ.get('ADMIN_USER_ID')
        
        # 統計情報を計算（エラーハンドリング強化）
        try:
            personal_statistics = calculate_work_hours_statistics(user.id)
        except Exception as e:
            logger.error(f"Error calculating personal statistics: {e}")
            personal_statistics = {'average_hours': 0, 'median_hours': 0, 'total_hours': 0, 'total_weeks': 0}
        
        try:
            overall_statistics = calculate_work_hours_statistics()  # 全体統計
        except Exception as e:
            logger.error(f"Error calculating overall statistics: {e}")
            overall_statistics = {'average_hours': 0, 'median_hours': 0, 'total_hours': 0, 'total_weeks': 0}

        return render_template('index.html', 
                             user=user, 
                             attendances=attendances, 
                             admin_user_id=admin_user_id,
                             personal_statistics=personal_statistics,
                             overall_statistics=overall_statistics)
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
    """Slack認証ページ（Modern Sign in with Slack - OpenID Connect）"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    # Modern Sign in with Slack (OpenID Connect) のURL
    client_id = os.environ.get('SLACK_CLIENT_ID')
    # OpenID Connect スコープ: openid（必須）, profile（ユーザー名・チーム情報）, email（メールアドレス）
    scope = 'openid profile email'
    redirect_uri = url_for('callback', _external=True)
    
    slack_oauth_url = f"https://slack.com/openid/connect/authorize?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}&response_type=code"
    
    return render_template('login.html', oauth_url=slack_oauth_url)

@app.route('/callback')
def callback():
    """Slack認証後のコールバック（Modern Sign in with Slack - OpenID Connect）"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        logger.error(f"OAuth error: {error}")
        flash(f'認証エラー: {error}', 'error')
        return redirect(url_for('login'))
    
    if not code:
        logger.error("Authorization code not received")
        flash('認証コードが受信されませんでした。', 'error')
        return redirect(url_for('login'))
    
    try:
        # Modern Sign in with Slack (OpenID Connect) のトークン交換エンドポイント
        token_url = "https://slack.com/api/openid.connect.token"
        
        token_data = {
            'client_id': os.environ.get('SLACK_CLIENT_ID'),
            'client_secret': os.environ.get('SLACK_CLIENT_SECRET'),
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': url_for('callback', _external=True)
        }
        
        response = requests.post(token_url, data=token_data)
        token_response = response.json()
        
        if not token_response.get('ok', False):
            logger.error(f"Token exchange failed: {token_response}")
            flash('認証に失敗しました。', 'error')
            return redirect(url_for('login'))
        
        access_token = token_response.get('access_token')
        id_token = token_response.get('id_token')  # JWT形式のIDトークン
        
        if not access_token:
            logger.error("Access token not received")
            flash('アクセストークンが受信されませんでした。', 'error')
            return redirect(url_for('login'))
        
        # OpenID Connect userInfo エンドポイントでユーザー情報を取得
        user_info_url = "https://slack.com/api/openid.connect.userInfo"
        headers = {'Authorization': f'Bearer {access_token}'}
        
        user_response = requests.get(user_info_url, headers=headers)
        user_data = user_response.json()
        
        if not user_data.get('ok', False):
            logger.error(f"User info request failed: {user_data}")
            flash('ユーザー情報の取得に失敗しました。', 'error')
            return redirect(url_for('login'))
        
        # OpenID Connect レスポンスから必要な情報を取得
        slack_user_id = user_data.get('sub')  # OpenID Connect標準のsubject ID
        user_name = user_data.get('name', 'Unknown User')
        user_email = user_data.get('email', '')
        team_id = user_data.get('https://slack.com/team_id')
        
        if not slack_user_id:
            logger.error("Slack user ID not found in response")
            flash('ユーザーIDの取得に失敗しました。', 'error')
            return redirect(url_for('login'))
        
        # ユーザーを取得または作成
        user = User.query.filter_by(slack_user_id=slack_user_id).first()
        
        if not user:
            user = User(
                slack_user_id=slack_user_id,
                display_name=user_name,
                email=user_email
            )
            db.session.add(user)
            db.session.commit()
            logger.info(f"Created new user: {slack_user_id}")
        else:
            # 既存ユーザーの情報を更新
            user.display_name = user_name
            user.email = user_email
            db.session.commit()
            logger.info(f"Updated user info: {slack_user_id}")
        
        # セッションに保存
        session.permanent = True  # セッションを永続化
        session['user_id'] = user.id
        session['slack_user_id'] = slack_user_id
        session['user_name'] = user_name
        session['team_id'] = team_id
        
        flash(f'{user_name} さん、ようこそ！', 'success')
        return redirect(url_for('index'))
        
    except requests.RequestException as e:
        logger.error(f"Request error during OAuth: {e}")
        flash('認証処理中にネットワークエラーが発生しました。', 'error')
        return redirect(url_for('login'))
    except Exception as e:
        logger.error(f"Unexpected error during OAuth: {e}")
        flash('認証処理中に予期しないエラーが発生しました。', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    """ログアウト処理"""
    session.clear()
    flash('ログアウトしました。', 'info')
    return redirect(url_for('login'))

@app.route('/attendance/add', methods=['POST'])
def add_attendance():
    """出退勤記録の新規追加"""
    if 'user_id' not in session:
        return jsonify({'error': 'ログインが必要です'}), 401
    
    try:
        data = request.get_json()
        
        if not data.get('type') or not data.get('timestamp'):
            return jsonify({'error': '種別と日時は必須です'}), 400
        
        if data['type'] not in ['出勤', '退勤']:
            return jsonify({'error': '種別は「出勤」または「退勤」である必要があります'}), 400
        
        try:
            timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': '日時の形式が正しくありません'}), 400
        
        # 新規出退勤記録を作成
        attendance = Attendance(
            user_id=session['user_id'],
            type=data['type'],
            timestamp=timestamp
        )
        
        db.session.add(attendance)
        db.session.commit()
        
        return jsonify({'message': '記録を追加しました', 'attendance': attendance.to_dict()})
    except Exception as e:
        logger.error(f"Error adding attendance: {e}")
        return jsonify({'error': '追加中にエラーが発生しました'}), 500

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
        
        # 全体の統計情報を計算（エラーハンドリング強化）
        try:
            statistics_data = calculate_work_hours_statistics()
        except Exception as e:
            logger.error(f"Error calculating admin statistics: {e}")
            statistics_data = {'average_hours': 0, 'median_hours': 0, 'total_hours': 0, 'total_weeks': 0}
        
        return render_template('admin.html', 
                             attendances=attendances,
                             statistics=statistics_data,
                             admin_user_id=admin_user_id)
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
    # Gunicornから起動される場合（本番環境）
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    create_app()

if __name__ == '__main__':
    # 開発環境での直接実行
    create_app()
    app.run(debug=True, host='0.0.0.0', port=5000) 