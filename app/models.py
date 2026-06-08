from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # 'admin' or 'user'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    vouchers = db.relationship('Voucher', backref='owner', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Voucher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'coupon', 'gift_card', 'membership'
    code = db.Column(db.String(200))
    balance = db.Column(db.Float, default=0.0)
    face_value = db.Column(db.Float, default=0.0)
    expiry_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)
    attachment_path = db.Column(db.String(500))
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    history = db.relationship('VoucherHistory', backref='voucher', lazy='dynamic',
                              order_by='VoucherHistory.created_at.desc()')

    TYPE_CHOICES = [
        ('coupon', '优惠券'),
        ('gift_card', '礼品卡'),
        ('membership', '会员卡'),
    ]

    @property
    def type_display(self):
        return dict(self.TYPE_CHOICES).get(self.type, self.type)

    @property
    def is_expired(self):
        if self.expiry_date is None:
            return False
        return self.expiry_date < datetime.now(timezone.utc).date()


class VoucherHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('voucher.id'), nullable=False, index=True)
    modified_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    field_name = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.String(200))
    new_value = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    modifier = db.relationship('User', foreign_keys=[modified_by])
