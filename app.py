import os
import re
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, jsonify, session, flash
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from models import db, User, Attendance
from dotenv import load_dotenv
import threading
import requests

# 環境変数を読み込み
load_dotenv()

# Flaskアプリケーションの設定
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# データベースの初期化
db.init_app(app)

# Slack Boltアプリケーションの設定
slack_app = App(
    token=os.environ.get('SLACK_BOT_TOKEN'),
    signing_secret=os.environ.get('SLACK_SIGNING_SECRET')
)

# Slack Web クライアント
slack_client = WebClient(token=os.environ.get('SLACK_BOT_TOKEN'))

# SlackRequestHandlerの設定
handler = SlackRequestHandler(slack_app)

# データベースの初期化は起動時に実行

# Slack Bot イベントリスナー
@slack_app.message(re.compile(r'(出勤|おはよう)', re.IGNORECASE))
def handle_checkin(message, say):
    """出勤打刻を処理"""
    user_id = message['user']
    
    # ユーザー情報を取得
    user = get_or_create_user(user_id)
    
    # 出勤記録を作成
    attendance = Attendance(
        user_id=user.id,
        type='出勤',
        timestamp=datetime.now()
    )
    
    db.session.add(attendance)
    db.session.commit()
    
    # 返信メッセージを送信
    say(f"出勤打刻を受け付けました！ {attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

@slack_app.message(re.compile(r'(退勤|おつかれ)', re.IGNORECASE))
def handle_checkout(message, say):
    """退勤打刻を処理"""
    user_id = message['user']
    
    # ユーザー情報を取得
    user = get_or_create_user(user_id)
    
    # 退勤記録を作成
    attendance = Attendance(
        user_id=user.id,
        type='退勤',
        timestamp=datetime.now()
    )
    
    db.session.add(attendance)
    db.session.commit()
    
    # 返信メッセージを送信
    say(f"退勤打刻を受け付けました！ {attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

def get_or_create_user(slack_user_id):
    """Slackユーザー情報を取得または作成"""
    user = User.query.filter_by(slack_user_id=slack_user_id).first()
    
    if not user:
        try:
            # Slack APIからユーザー情報を取得
            response = slack_client.users_info(user=slack_user_id)
            user_info = response['user']
            
            user = User(
                slack_user_id=slack_user_id,
                display_name=user_info.get('real_name', user_info.get('name', 'Unknown')),
                email=user_info.get('profile', {}).get('email', '')
            )
            
            db.session.add(user)
            db.session.commit()
            
        except SlackApiError as e:
            print(f"Error fetching user info: {e}")
            # エラーの場合はデフォルトユーザーを作成
            user = User(
                slack_user_id=slack_user_id,
                display_name=f'User_{slack_user_id}',
                email=''
            )
            db.session.add(user)
            db.session.commit()
    
    return user

# Webアプリケーションのルート
@app.route('/')
def index():
    """ログイン後の出退勤一覧ページ"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    # ユーザーの出退勤記録を取得（最新順）
    attendances = Attendance.query.filter_by(user_id=user.id).order_by(Attendance.timestamp.desc()).all()
    
    return render_template('index.html', user=user, attendances=attendances)

@app.route('/login')
def login():
    """Slack認証ページ"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    # Slack OAuthのURL
    client_id = os.environ.get('SLACK_CLIENT_ID')
    scope = 'identity.basic,identity.email'
    redirect_uri = url_for('callback', _external=True)
    
    slack_oauth_url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}"
    
    return render_template('login.html', oauth_url=slack_oauth_url)

@app.route('/callback')
def callback():
    """Slack認証後のコールバック"""
    code = request.args.get('code')
    
    if not code:
        flash('認証に失敗しました。', 'error')
        return redirect(url_for('login'))
    
    try:
        # OAuth認証のトークン取得
        response = requests.post('https://slack.com/api/oauth.v2.access', {
            'client_id': os.environ.get('SLACK_CLIENT_ID'),
            'client_secret': os.environ.get('SLACK_CLIENT_SECRET'),
            'code': code,
            'redirect_uri': url_for('callback', _external=True)
        })
        
        auth_data = response.json()
        
        if auth_data.get('ok'):
            # ユーザー情報取得
            user_token = auth_data['authed_user']['access_token']
            user_info_response = requests.get(
                'https://slack.com/api/users.identity',
                headers={'Authorization': f'Bearer {user_token}'}
            )
            
            user_info = user_info_response.json()
            
            if user_info.get('ok'):
                slack_user_id = user_info['user']['id']
                
                # ユーザーを取得または作成
                user = User.query.filter_by(slack_user_id=slack_user_id).first()
                
                if not user:
                    user = User(
                        slack_user_id=slack_user_id,
                        display_name=user_info['user']['name'],
                        email=user_info['user'].get('email', '')
                    )
                    db.session.add(user)
                    db.session.commit()
                
                # セッションに保存
                session['user_id'] = user.id
                session['slack_user_id'] = slack_user_id
                
                flash('ログインしました。', 'success')
                return redirect(url_for('index'))
        
        flash('認証に失敗しました。', 'error')
        return redirect(url_for('login'))
        
    except Exception as e:
        print(f"OAuth callback error: {e}")
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
    
    attendance.updated_at = datetime.now()
    db.session.commit()
    
    return jsonify({'message': '更新しました', 'attendance': attendance.to_dict()})

@app.route('/attendance/delete/<int:id>', methods=['DELETE'])
def delete_attendance(id):
    """出退勤記録の削除"""
    if 'user_id' not in session:
        return jsonify({'error': 'ログインが必要です'}), 401
    
    attendance = Attendance.query.get(id)
    if not attendance:
        return jsonify({'error': '記録が見つかりません'}), 404
    
    # 所有者チェック
    if attendance.user_id != session['user_id']:
        return jsonify({'error': '権限がありません'}), 403
    
    db.session.delete(attendance)
    db.session.commit()
    
    return jsonify({'message': '削除しました'})

@app.route('/admin')
def admin():
    """管理者用の全ユーザー出退勤一覧ページ"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 管理者チェック
    user = User.query.get(session['user_id'])
    admin_user_id = os.environ.get('ADMIN_USER_ID')
    
    if not user or user.slack_user_id != admin_user_id:
        flash('管理者権限が必要です。', 'error')
        return redirect(url_for('index'))
    
    # 全ユーザーの出退勤記録を取得
    attendances = db.session.query(Attendance, User).join(User).order_by(Attendance.timestamp.desc()).all()
    
    return render_template('admin.html', attendances=attendances)

# Slack イベントエンドポイント
@app.route('/slack/events', methods=['POST'])
def slack_events():
    """Slack イベントを処理"""
    return handler.handle(request)

# データベース初期化コマンド
@app.cli.command()
def init_db():
    """データベースを初期化"""
    db.create_all()
    print('データベースが初期化されました。')

if __name__ == '__main__':
    # データベースの初期化
    with app.app_context():
        db.create_all()
    
    # Flaskアプリケーションの起動
    app.run(debug=True, host='0.0.0.0', port=5000) 