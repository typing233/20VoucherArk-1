from datetime import datetime, timedelta, timezone

from flask import render_template, current_app, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.main import bp
from app.models import Voucher


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now(timezone.utc).date()
    week_later = today + timedelta(days=7)
    threshold = current_app.config['LOW_BALANCE_THRESHOLD']

    base_query = Voucher.query.filter_by(user_id=current_user.id, is_deleted=False)

    expiring_soon = base_query.filter(
        Voucher.expiry_date >= today,
        Voucher.expiry_date <= week_later
    ).order_by(Voucher.expiry_date.asc()).all()

    expired = base_query.filter(
        Voucher.expiry_date < today
    ).order_by(Voucher.expiry_date.desc()).limit(10).all()

    low_balance = base_query.filter(
        Voucher.balance > 0,
        Voucher.balance <= threshold
    ).order_by(Voucher.balance.asc()).all()

    total = base_query.count()

    return render_template('main/dashboard.html',
                           expiring_soon=expiring_soon,
                           expired=expired,
                           low_balance=low_balance,
                           total=total)
