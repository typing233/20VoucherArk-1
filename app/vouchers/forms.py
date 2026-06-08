from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, SelectField, FloatField, DateField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, NumberRange


class VoucherForm(FlaskForm):
    name = StringField('名称', validators=[DataRequired(), ])
    type = SelectField('类型', choices=[
        ('coupon', '优惠券'),
        ('gift_card', '礼品卡'),
        ('membership', '会员卡'),
    ], validators=[DataRequired()])
    code = StringField('卡号/券码', validators=[Optional()])
    balance = FloatField('余额', validators=[Optional(), NumberRange(min=0)], default=0.0)
    face_value = FloatField('面值', validators=[Optional(), NumberRange(min=0)], default=0.0)
    expiry_date = DateField('有效期', validators=[Optional()], format='%Y-%m-%d')
    notes = TextAreaField('备注', validators=[Optional()])
    attachment = FileField('附件', validators=[
        FileAllowed(['png', 'jpg', 'jpeg', 'gif', 'pdf', 'webp'], '仅支持图片和PDF文件')
    ])
    submit = SubmitField('保存')


class BalanceEditForm(FlaskForm):
    balance = FloatField('余额', validators=[Optional(), NumberRange(min=0)])
    face_value = FloatField('面值', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('更新')
