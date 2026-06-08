import os
import io
import pytest
from app import create_app, db
from app.models import User, Voucher
from config import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app, client):
    with app.app_context():
        user = User(username='testuser', email='test@test.com')
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()
    client.post('/auth/login', data={'username': 'testuser', 'password': 'password123'})
    return client


class TestAuth:
    def test_register(self, client):
        resp = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'new@test.com',
            'password': 'password123',
            'password2': 'password123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '注册成功' in resp.data.decode()

    def test_login(self, app, client):
        with app.app_context():
            user = User(username='loginuser', email='login@test.com')
            user.set_password('pass123')
            db.session.add(user)
            db.session.commit()
        resp = client.post('/auth/login', data={
            'username': 'loginuser', 'password': 'pass123'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '仪表盘' in resp.data.decode()

    def test_login_wrong_password(self, app, client):
        with app.app_context():
            user = User(username='user2', email='u2@test.com')
            user.set_password('correct')
            db.session.add(user)
            db.session.commit()
        resp = client.post('/auth/login', data={
            'username': 'user2', 'password': 'wrong'
        }, follow_redirects=True)
        assert '用户名或密码错误' in resp.data.decode()

    def test_protected_route(self, client):
        resp = client.get('/vouchers/', follow_redirects=True)
        assert '登录' in resp.data.decode()


class TestVouchers:
    def test_create_voucher(self, app, auth_client):
        resp = auth_client.post('/vouchers/create', data={
            'name': '测试优惠券',
            'type': 'coupon',
            'code': 'ABC123',
            'balance': '100',
            'face_value': '100',
            'expiry_date': '2027-12-31',
            'notes': '测试备注',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            v = Voucher.query.filter_by(name='测试优惠券').first()
            assert v is not None
            assert v.code == 'ABC123'
            assert v.balance == 100.0

    def test_list_vouchers(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            v = Voucher(user_id=user.id, name='列表测试', type='gift_card', balance=50)
            db.session.add(v)
            db.session.commit()
        resp = auth_client.get('/vouchers/')
        assert '列表测试' in resp.data.decode()

    def test_search_vouchers(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            db.session.add(Voucher(user_id=user.id, name='星巴克卡', type='gift_card', balance=200))
            db.session.add(Voucher(user_id=user.id, name='麦当劳券', type='coupon', balance=30))
            db.session.commit()
        resp = auth_client.get('/vouchers/?search=星巴克')
        data = resp.data.decode()
        assert '星巴克卡' in data
        assert '麦当劳券' not in data

    def test_type_filter(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            db.session.add(Voucher(user_id=user.id, name='礼品A', type='gift_card'))
            db.session.add(Voucher(user_id=user.id, name='优惠B', type='coupon'))
            db.session.commit()
        resp = auth_client.get('/vouchers/?type=gift_card')
        data = resp.data.decode()
        assert '礼品A' in data
        assert '优惠B' not in data

    def test_soft_delete_and_restore(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            v = Voucher(user_id=user.id, name='待删除', type='coupon')
            db.session.add(v)
            db.session.commit()
            vid = v.id

        auth_client.post(f'/vouchers/{vid}/delete')
        with app.app_context():
            v = db.session.get(Voucher, vid)
            assert v.is_deleted is True

        auth_client.post(f'/vouchers/{vid}/restore')
        with app.app_context():
            v = db.session.get(Voucher, vid)
            assert v.is_deleted is False

    def test_edit_balance_with_history(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            v = Voucher(user_id=user.id, name='余额测试', type='gift_card', balance=100, face_value=200)
            db.session.add(v)
            db.session.commit()
            vid = v.id

        auth_client.post(f'/vouchers/{vid}/edit-balance', data={
            'balance': '80',
            'face_value': '200',
        })
        with app.app_context():
            v = db.session.get(Voucher, vid)
            assert v.balance == 80.0
            history = v.history.all()
            assert len(history) == 1
            assert history[0].field_name == 'balance'
            assert history[0].old_value == '100.0'
            assert history[0].new_value == '80.0'

    def test_data_isolation(self, app, client):
        with app.app_context():
            user1 = User(username='user_a', email='a@test.com')
            user1.set_password('pass')
            user2 = User(username='user_b', email='b@test.com')
            user2.set_password('pass')
            db.session.add_all([user1, user2])
            db.session.commit()
            v = Voucher(user_id=user1.id, name='User_A_卡', type='coupon')
            db.session.add(v)
            db.session.commit()
            vid = v.id

        client.post('/auth/login', data={'username': 'user_b', 'password': 'pass'})
        resp = client.get('/vouchers/')
        assert 'User_A_卡' not in resp.data.decode()
        resp = client.get(f'/vouchers/{vid}')
        assert resp.status_code == 403

    def test_csv_export(self, app, auth_client):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            db.session.add(Voucher(user_id=user.id, name='导出测试', type='coupon', balance=50))
            db.session.commit()
        resp = auth_client.get('/vouchers/export')
        assert resp.status_code == 200
        assert '导出测试' in resp.data.decode('utf-8-sig')

    def test_csv_import(self, app, auth_client):
        csv_content = '名称,类型,卡号/券码,余额,面值,有效期,备注\n导入卡,礼品卡,IMP001,200,200,2027-06-01,测试导入\n'
        data = {'file': (io.BytesIO(csv_content.encode('utf-8-sig')), 'test.csv')}
        resp = auth_client.post('/vouchers/import', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        assert '成功导入' in resp.data.decode()
        with app.app_context():
            v = Voucher.query.filter_by(name='导入卡').first()
            assert v is not None
            assert v.balance == 200.0

    def test_upload_attachment(self, app, auth_client):
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        data = {
            'name': '带附件',
            'type': 'gift_card',
            'balance': '0',
            'face_value': '0',
            'attachment': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100), 'test.png'),
        }
        resp = auth_client.post('/vouchers/create', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            v = Voucher.query.filter_by(name='带附件').first()
            assert v is not None
            assert v.attachment_path is not None
            assert v.attachment_path.endswith('.png')

    def test_edit_page_records_balance_history(self, app, auth_client):
        """Fix 1: editing balance via the general edit page must record history."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            v = Voucher(user_id=user.id, name='编辑历史测试', type='gift_card',
                        balance=500, face_value=1000)
            db.session.add(v)
            db.session.commit()
            vid = v.id

        auth_client.post(f'/vouchers/{vid}/edit', data={
            'name': '编辑历史测试',
            'type': 'gift_card',
            'balance': '300',
            'face_value': '800',
        }, follow_redirects=True)

        with app.app_context():
            v = db.session.get(Voucher, vid)
            assert v.balance == 300.0
            assert v.face_value == 800.0
            history = v.history.order_by(None).all()
            assert len(history) == 2
            fields = {h.field_name for h in history}
            assert fields == {'balance', 'face_value'}

    def test_reject_fake_extension(self, app, auth_client):
        """Fix 4: file with wrong magic bytes should be rejected."""
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        data = {
            'name': '假图片',
            'type': 'coupon',
            'balance': '0',
            'face_value': '0',
            'attachment': (io.BytesIO(b'this is not a png file'), 'fake.png'),
        }
        resp = auth_client.post('/vouchers/create', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        assert '文件类型与后缀不匹配' in resp.data.decode()
        with app.app_context():
            v = Voucher.query.filter_by(name='假图片').first()
            assert v is None

    def test_pdf_upload_valid(self, app, auth_client):
        """Fix 4: valid PDF with correct magic bytes should be accepted."""
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        pdf_content = b'%PDF-1.4 fake pdf content for testing'
        data = {
            'name': 'PDF测试',
            'type': 'coupon',
            'balance': '0',
            'face_value': '0',
            'attachment': (io.BytesIO(pdf_content), 'test.pdf'),
        }
        resp = auth_client.post('/vouchers/create', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            v = Voucher.query.filter_by(name='PDF测试').first()
            assert v is not None
            assert v.attachment_path.endswith('.pdf')
