from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class User(db.Model):
    """Slackユーザー情報を保存するモデル"""
    id = db.Column(db.Integer, primary_key=True)
    slack_user_id = db.Column(db.String(20), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # リレーションシップ
    attendances = db.relationship('Attendance', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.display_name}>'

class Attendance(db.Model):
    """出退勤記録を保存するモデル"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # '出勤' or '退勤'
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<Attendance {self.type} - {self.timestamp}>'
    
    def to_dict(self):
        """オブジェクトを辞書形式で返す"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.type,
            'timestamp': self.timestamp.isoformat(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        } 