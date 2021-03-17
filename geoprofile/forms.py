from flask_wtf import FlaskForm
from wtforms import FileField, StringField, FloatField, IntegerField, FieldList, BooleanField
from wtforms.validators import DataRequired, AnyOf, Optional
import contextily as ctx


RESPONSE_ERROR_INPUT_MESSAGE = "Permitted values for response are prompt or deferred"


class BaseProfileForm(FlaskForm):
    response = StringField('response',
                           validators=[Optional(), AnyOf(['prompt', 'deferred'], RESPONSE_ERROR_INPUT_MESSAGE)],
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

    crs = StringField('crs', validators=[Optional()])
    geometry = StringField('geometry', validators=[Optional()], default='wkt')

    class Meta:
        csrf = False


class ProfileFileForm(BaseProfileForm):
    resource = FileField('resource', validators=[DataRequired()])


class ProfilePathForm(BaseProfileForm):
    resource = StringField('resource', validators=[DataRequired()])


class BaseNormalizeForm(FlaskForm):
    resource_type = StringField('resource_type', validators=[DataRequired(),
                                                             AnyOf(['csv', 'shp'],
                                                                   "Permitted values for resource_type are csv or shp")])
    csv_delimiter = StringField('csv_delimiter', validators=[Optional()])
    crs = StringField('crs', validators=[Optional()])
    response = StringField('response',
                           validators=[Optional(),
                                       AnyOf(['prompt', 'deferred'], RESPONSE_ERROR_INPUT_MESSAGE)],
                           default='prompt')

    date_normalization = FieldList(StringField('date_normalization', validators=[Optional()], default=[]),
                                   min_entries=0, validators=[Optional()])
    phone_normalization = FieldList(StringField('phone_normalization', validators=[Optional()], default=[]),
                                    min_entries=0, validators=[Optional()])
    special_character_normalization = FieldList(StringField('special_character_normalization', validators=[Optional()], default=[]),
                                                min_entries=0, validators=[Optional()])
    alphabetical_normalization = FieldList(StringField('alphabetical_normalization', validators=[Optional()], default=[]),
                                           min_entries=0, validators=[Optional()])
    case_normalization = FieldList(StringField('case_normalization', validators=[Optional()], default=[]),
                                   min_entries=0, validators=[Optional()])
    transliteration = FieldList(StringField('transliteration', validators=[Optional()], default=[]),
                                min_entries=0, validators=[Optional()])
    transliteration_langs = FieldList(StringField('transliteration_langs', validators=[Optional()], default=[]),
                                      min_entries=0, validators=[Optional()])
    transliteration_lang = StringField('transliteration_lang', validators=[Optional()], default='')
    value_cleaning = FieldList(StringField('value_cleaning', validators=[Optional()], default=[]),
                               min_entries=0, validators=[Optional()])
    wkt_normalization = BooleanField('wkt_normalization', validators=[Optional()])
    column_name_normalization = BooleanField('column_name_normalization', validators=[Optional()])

    class Meta:
        csrf = False


class NormalizeFileForm(BaseNormalizeForm):
    resource = FileField('resource', validators=[DataRequired()])


class NormalizePathForm(BaseNormalizeForm):
    resource = StringField('resource', validators=[DataRequired()])


class BaseSummarizeForm(FlaskForm):
    resource_type = StringField('resource_type', validators=[DataRequired(),
                                                             AnyOf(['csv', 'shp'],
                                                                   "Permitted values for resource_type are csv or shp")])
    csv_delimiter = StringField('csv_delimiter', validators=[Optional()])
    crs = StringField('crs', validators=[Optional()])
    response = StringField('response',
                           validators=[Optional(),
                                       AnyOf(['prompt', 'deferred'], RESPONSE_ERROR_INPUT_MESSAGE)],
                           default='prompt')
    sampling_method = StringField('sampling_method', validators=[Optional(),
                                                                 AnyOf(['random', 'stratified', 'cluster'],
                                                                       "Permitted values for sampling_method are random, stratified and cluster")],
                                  default='random')
    columns_to_sample = FieldList(StringField('columns_to_sample', validators=[Optional()], default=[]),
                                  min_entries=0, validators=[Optional()])
    n_samples = IntegerField('n_samples', validators=[Optional()], )
    n_clusters = IntegerField('n_clusters', validators=[Optional()])
    n_sample_per_cluster = IntegerField('n_sample_per_cluster', validators=[Optional()])
    clustering_column_name = StringField('clustering_column_name', validators=[Optional()])
    to_stratify = FieldList(StringField('to_stratify', validators=[Optional()], default=[]),
                            min_entries=0, validators=[Optional()])
    columns_to_hist = FieldList(StringField('to_stratify', validators=[Optional()], default=[]),
                                min_entries=0, validators=[Optional()])
    n_buckets = IntegerField('n_buckets', validators=[Optional()])

    class Meta:
        csrf = False


class SummarizeFileForm(BaseSummarizeForm):
    resource = FileField('resource', validators=[DataRequired()])


class SummarizePathForm(BaseSummarizeForm):
    resource = StringField('resource', validators=[DataRequired()])
