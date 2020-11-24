from flask_wtf import FlaskForm
from wtforms import FileField, StringField
from wtforms.validators import DataRequired, AnyOf, Optional


class BaseForm(FlaskForm):
    response = StringField('response',
                           validators=[Optional(),
                                       AnyOf(['prompt', 'deferred'],
                                             "Permitted values for response are prompt or deferred")], default='prompt')

    class Meta:
        csrf = False


class ProfileFileForm(BaseForm):
    resource = FileField('resource', validators=[DataRequired()])


class ProfilePathForm(BaseForm):
    resource = StringField('resource', validators=[DataRequired()])
