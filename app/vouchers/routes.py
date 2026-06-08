import os
import uuid
import csv
import io
from datetime import datetime, timedelta, timezone

from flask import (render_template, redirect, url_for, flash, request,
                   current_app, send_from_directory, abort)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.vouchers import bp
from app.vouchers.forms import VoucherForm, BalanceEditForm
from app.models import Voucher, VoucherHistory

MAGIC_BYTES = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'pdf': [b'%PDF'],
    'webp': [b'RIFF'],
}


def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS'])


def validate_file_type(file_storage):
    """Check file's real type via magic bytes. Returns True if valid."""
    if not file_storage or not file_storage.filename:
        return False
    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    if ext not in current_app.config['ALLOWED_EXTENSIONS']:
        return False
    header = file_storage.read(16)
    file_storage.seek(0)
    if not header:
        return False
    signatures = MAGIC_BYTES.get(ext, [])
    if not signatures:
        return False
    return any(header.startswith(sig) for sig in signatures)


def save_attachment(file):
    if not file or not file.filename:
        return None
    if not validate_file_type(file):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return filename


def delete_attachment(filename):
    if not filename:
        return True
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            return False
    return True


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    type_filter = request.args.get('type', '')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'expiry_asc')
    show_deleted = request.args.get('deleted', '0') == '1'

    query = Voucher.query.filter_by(user_id=current_user.id)

    if show_deleted:
        query = query.filter_by(is_deleted=True)
    else:
        query = query.filter_by(is_deleted=False)

    if type_filter:
        query = query.filter_by(type=type_filter)

    if search:
        query = query.filter(
            db.or_(
                Voucher.name.ilike(f'%{search}%'),
                Voucher.code.ilike(f'%{search}%'),
                Voucher.notes.ilike(f'%{search}%'),
            )
        )

    if sort == 'expiry_desc':
        query = query.order_by(Voucher.expiry_date.desc().nullslast())
    else:
        query = query.order_by(Voucher.expiry_date.asc().nullslast())

    pagination = query.paginate(
        page=page, per_page=current_app.config['VOUCHERS_PER_PAGE'], error_out=False
    )

    return render_template('vouchers/index.html',
                           vouchers=pagination.items,
                           pagination=pagination,
                           type_filter=type_filter,
                           search=search,
                           sort=sort,
                           show_deleted=show_deleted)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = VoucherForm()
    if form.validate_on_submit():
        attachment_name = None
        if form.attachment.data and form.attachment.data.filename:
            attachment_name = save_attachment(form.attachment.data)
            if attachment_name is None:
                flash('附件格式不支持或文件类型与后缀不匹配', 'danger')
                return render_template('vouchers/form.html', form=form, title='新建卡券')

        voucher = Voucher(
            user_id=current_user.id,
            name=form.name.data,
            type=form.type.data,
            code=form.code.data,
            balance=form.balance.data or 0.0,
            face_value=form.face_value.data or 0.0,
            expiry_date=form.expiry_date.data,
            notes=form.notes.data,
            attachment_path=attachment_name,
        )
        try:
            db.session.add(voucher)
            db.session.commit()
            flash('卡券创建成功', 'success')
            return redirect(url_for('vouchers.index'))
        except Exception:
            db.session.rollback()
            if attachment_name:
                delete_attachment(attachment_name)
            flash('创建失败，请重试', 'danger')

    return render_template('vouchers/form.html', form=form, title='新建卡券')


@bp.route('/<int:id>')
@login_required
def detail(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    history = voucher.history.all()
    return render_template('vouchers/detail.html', voucher=voucher, history=history)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    form = VoucherForm(obj=voucher)
    if form.validate_on_submit():
        old_attachment = voucher.attachment_path
        new_attachment = None

        if form.attachment.data and form.attachment.data.filename:
            new_attachment = save_attachment(form.attachment.data)
            if new_attachment is None:
                flash('附件格式不支持或文件类型与后缀不匹配', 'danger')
                return render_template('vouchers/form.html', form=form, title='编辑卡券')

        # Track balance/face_value changes
        new_balance = form.balance.data or 0.0
        new_face_value = form.face_value.data or 0.0
        balance_changes = []
        if new_balance != voucher.balance:
            balance_changes.append(('balance', str(voucher.balance), str(new_balance)))
        if new_face_value != voucher.face_value:
            balance_changes.append(('face_value', str(voucher.face_value), str(new_face_value)))

        voucher.name = form.name.data
        voucher.type = form.type.data
        voucher.code = form.code.data
        voucher.balance = new_balance
        voucher.face_value = new_face_value
        voucher.expiry_date = form.expiry_date.data
        voucher.notes = form.notes.data

        if new_attachment:
            voucher.attachment_path = new_attachment

        for field_name, old_val, new_val in balance_changes:
            history = VoucherHistory(
                voucher_id=voucher.id,
                modified_by=current_user.id,
                field_name=field_name,
                old_value=old_val,
                new_value=new_val,
            )
            db.session.add(history)

        try:
            db.session.commit()
            if new_attachment and old_attachment:
                if not delete_attachment(old_attachment):
                    flash('警告：旧附件文件删除失败，请联系管理员清理磁盘残留文件', 'warning')
            flash('卡券更新成功', 'success')
            return redirect(url_for('vouchers.detail', id=voucher.id))
        except Exception:
            db.session.rollback()
            if new_attachment:
                delete_attachment(new_attachment)
            flash('更新失败，请重试', 'danger')

    return render_template('vouchers/form.html', form=form, title='编辑卡券')


@bp.route('/<int:id>/edit-balance', methods=['GET', 'POST'])
@login_required
def edit_balance(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    form = BalanceEditForm(obj=voucher)
    if form.validate_on_submit():
        changes = []
        if form.balance.data is not None and form.balance.data != voucher.balance:
            changes.append(('balance', str(voucher.balance), str(form.balance.data)))
            voucher.balance = form.balance.data
        if form.face_value.data is not None and form.face_value.data != voucher.face_value:
            changes.append(('face_value', str(voucher.face_value), str(form.face_value.data)))
            voucher.face_value = form.face_value.data

        if changes:
            for field_name, old_val, new_val in changes:
                history = VoucherHistory(
                    voucher_id=voucher.id,
                    modified_by=current_user.id,
                    field_name=field_name,
                    old_value=old_val,
                    new_value=new_val,
                )
                db.session.add(history)
            try:
                db.session.commit()
                flash('余额/面值已更新', 'success')
            except Exception:
                db.session.rollback()
                flash('更新失败', 'danger')
        else:
            flash('未检测到变化', 'info')

        return redirect(url_for('vouchers.detail', id=voucher.id))

    return render_template('vouchers/edit_balance.html', form=form, voucher=voucher)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    voucher.is_deleted = True
    db.session.commit()
    flash('卡券已删除（可恢复）', 'success')
    return redirect(url_for('vouchers.index'))


@bp.route('/<int:id>/restore', methods=['POST'])
@login_required
def restore(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    voucher.is_deleted = False
    db.session.commit()
    flash('卡券已恢复', 'success')
    return redirect(url_for('vouchers.index'))


@bp.route('/<int:id>/attachment')
@login_required
def download_attachment(id):
    voucher = Voucher.query.get_or_404(id)
    if voucher.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if not voucher.attachment_path:
        abort(404)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], voucher.attachment_path)


@bp.route('/export')
@login_required
def export_csv():
    vouchers = Voucher.query.filter_by(user_id=current_user.id, is_deleted=False).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['名称', '类型', '卡号/券码', '余额', '面值', '有效期', '备注'])
    for v in vouchers:
        writer.writerow([
            v.name, v.type_display, v.code or '',
            v.balance, v.face_value,
            v.expiry_date.isoformat() if v.expiry_date else '',
            v.notes or ''
        ])
    output.seek(0)
    from flask import Response
    return Response(
        '﻿' + output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=vouchers_export.csv'}
    )


@bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash('请上传CSV文件', 'danger')
            return redirect(url_for('vouchers.import_csv'))

        type_map = {'优惠券': 'coupon', '礼品卡': 'gift_card', '会员卡': 'membership'}
        try:
            content = file.stream.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            count = 0
            for row in reader:
                voucher = Voucher(
                    user_id=current_user.id,
                    name=row.get('名称', '').strip(),
                    type=type_map.get(row.get('类型', '').strip(), 'coupon'),
                    code=row.get('卡号/券码', '').strip() or None,
                    balance=float(row.get('余额', 0) or 0),
                    face_value=float(row.get('面值', 0) or 0),
                    expiry_date=datetime.strptime(row['有效期'], '%Y-%m-%d').date() if row.get('有效期', '').strip() else None,
                    notes=row.get('备注', '').strip() or None,
                )
                db.session.add(voucher)
                count += 1
            db.session.commit()
            flash(f'成功导入 {count} 条记录', 'success')
            return redirect(url_for('vouchers.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败: {str(e)}', 'danger')

    return render_template('vouchers/import.html')
