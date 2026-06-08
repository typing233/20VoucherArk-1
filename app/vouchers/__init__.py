from flask import Blueprint

bp = Blueprint('vouchers', __name__)

from app.vouchers import routes  # noqa: E402, F401
