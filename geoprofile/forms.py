from flask_wtf import FlaskForm
from wtforms import FileField, StringField, FloatField, IntegerField
from wtforms.validators import DataRequired, AnyOf, Optional
import contextily as ctx


class BaseForm(FlaskForm):
    response = StringField('response',
                           validators=[Optional(),
                                       AnyOf(['prompt', 'deferred'],
                                             "Permitted values for response are prompt or deferred")],
                           default='prompt')

    basemap_provider = StringField('basemap_provider',
                                   validators=[Optional(),
                                               AnyOf(list(ctx.providers.keys()),
                                                     "Default is (OpenStreetMap) permitted values are listed here "
                                                     "https://leaflet-extras.github.io/leaflet-providers/preview/")],
                                   default='OpenStreetMap')

    basemap_name = StringField('basemap_name', validators=[Optional()], default="Mapnik")

    aspect_ratio = FloatField('aspect_ratio', validators=[Optional()])
    width = IntegerField('width', validators=[Optional()])
    height = IntegerField('height', validators=[Optional()])

    lat = StringField('lat', validators=[Optional()])
    lon = StringField('lon', validators=[Optional()])
    time = StringField('time', validators=[Optional()])

    class Meta:
        csrf = False


class ProfileFileForm(BaseForm):
    resource = FileField('resource', validators=[DataRequired()])


class ProfilePathForm(BaseForm):
    resource = StringField('resource', validators=[DataRequired()])
