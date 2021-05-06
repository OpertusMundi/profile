import csv
import zipfile
import os
from flask import abort

from ..utils import mkdir
from .normalization_functions import date_normalization, column_name_normalization, value_cleaning, transliteration, \
    case_normalization, alphabetical_normalization, special_character_normalization, phone_normalization


def get_delimiter(ds_path: str) -> str:
    """ Returns the delimiter of the csv file """
    with open(ds_path) as f:
        first_line = f.readline()
        s = csv.Sniffer()
        return str(s.sniff(first_line).delimiter)


def make_zip(zip_name, path_to_zip):
    zip_handle = zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED)
    os.chdir(path_to_zip)
    for root, dirs, files in os.walk('.'):
        for file in files:
            zip_handle.write(os.path.join(root, file))


def perform_date_normalization(form, gdf):
    if form.date_normalization.data:
        for column in form.date_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: date_normalization(x))
    return gdf


def perform_phone_normalization(form, gdf):
    if form.phone_normalization.data:
        for column in form.phone_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: phone_normalization(x))
    return gdf


def perform_special_character_normalization(form, gdf):
    if form.special_character_normalization.data:
        for column in form.special_character_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: special_character_normalization(x))
    return gdf


def perform_alphabetical_normalization(form, gdf):
    if form.alphabetical_normalization.data:
        for column in form.alphabetical_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: alphabetical_normalization(x))
    return gdf


def perform_case_normalization(form, gdf):
    if form.case_normalization.data:
        for column in form.case_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: case_normalization(x))
    return gdf


def perform_transliteration(form, gdf):
    if form.transliteration.data:
        if form.transliteration_langs.data and form.transliteration_lang.data != '':
            langs = form.transliteration_langs.data + [form.transliteration_lang.data]
        elif form.transliteration_langs.data:
            langs = form.transliteration_langs.data
        elif form.transliteration_lang.data != '':
            langs = form.transliteration_lang.data
        else:
            abort(400, 'You selected the transliteration option without specifying the sources language(s)')
        for column in form.transliteration.data:
            gdf[column] = gdf[column].apply(lambda x: transliteration(x, langs))
    return gdf


def perform_value_cleaning(form, gdf):
    if form.value_cleaning.data:
        for column in form.value_cleaning.data:
            gdf[column] = gdf[column].apply(lambda x: value_cleaning(x))
    return gdf


def perform_wkt_normalization(form, gdf):
    if form.wkt_normalization.data:
        gdf.constructive.make_valid(inplace=True)
        gdf.constructive.normalize(inplace=True)
    return gdf


def perform_column_name_normalization(form, gdf):
    if form.column_name_normalization.data:
        gdf.columns = column_name_normalization(list(gdf.columns))
    return gdf


def normalize_gdf(form, gdf):
    gdf = perform_date_normalization(form, gdf)
    gdf = perform_phone_normalization(form, gdf)
    gdf = perform_special_character_normalization(form, gdf)
    gdf = perform_alphabetical_normalization(form, gdf)
    gdf = perform_case_normalization(form, gdf)
    gdf = perform_transliteration(form, gdf)
    gdf = perform_value_cleaning(form, gdf)
    gdf = perform_wkt_normalization(form, gdf)
    gdf = perform_column_name_normalization(form, gdf)
    return gdf


def store_gdf(gdf, resource_type, file_name, src_path) -> str:
    mkdir(src_path)
    if resource_type == "csv":
        stored_path = os.path.join(src_path, file_name + '.csv')
        gdf.export(stored_path)
        return stored_path
    elif resource_type == "shp":
        output_dir = os.path.join(src_path, file_name)
        mkdir(output_dir)
        gdf.export(os.path.join(output_dir, file_name + '.shp'), driver="ESRI ShapeFile")
        stored_path = os.path.join(output_dir + '.zip')
        make_zip(stored_path, output_dir)
        return stored_path
    else:
        abort(400, "Not supported file type, the supported ones are csv and shp")
