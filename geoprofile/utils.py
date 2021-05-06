import csv
import tarfile
import zipfile
import os
from tempfile import gettempdir, mkstemp
from uuid import uuid4
from os import path, makedirs, getenv

from bigdatavoyant import RasterData
from flask import abort
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename

import bigdatavoyant as bdv


def validate_form(form: FlaskForm, logger) -> None:
    if not form.validate_on_submit():
        logger.error(f'Error while parsing input parameters: {str(form.errors)}')
        abort(400, form.errors)


def create_ticket() -> str:
    ticket = str(uuid4())
    return ticket


def get_subdirectories(folder_path: str) -> list:
    subdirectories = []
    entry: os.DirEntry
    for entry in os.scandir(folder_path):
        if not entry.name.startswith('.') and entry.is_dir():
            subdirectories.append(entry.name)
    return subdirectories


def get_extracted_path(folder_path: str):
    extracted_path = folder_path
    subdirectories = get_subdirectories(folder_path)
    if len(subdirectories) == 0:
        return extracted_path
    else:
        return get_extracted_path(path.join(extracted_path, subdirectories[0]))


def uncompress_file(src_file: str) -> str:
    """Checks whether the file is compressed and uncompresses it"""
    try:
        if not path.isdir(src_file):
            src_path = path.dirname(src_file)
            if tarfile.is_tarfile(src_file):
                with tarfile.open(src_file, 'r') as handle:
                    handle.extractall(src_path)
                    extracted_path = get_extracted_path(src_path)
                    return extracted_path
            elif zipfile.is_zipfile(src_file):
                with zipfile.ZipFile(src_file, 'r') as handle:
                    handle.extractall(src_path)
                    extracted_path = get_extracted_path(src_path)
                    return extracted_path
        return src_file
    except FileNotFoundError:
        abort(400, 'File not found')


def mkdir(folder_path: str) -> None:
    """Creates recursively the path, ignoring warnings for existing directories."""
    try:
        makedirs(folder_path)
    except OSError:
        pass


def get_tmp_dir(namespace: str) -> str:
    tempdir = getenv('TEMPDIR') or gettempdir()
    tempdir = path.join(tempdir, namespace)
    mkdir(tempdir)
    return tempdir


def save_to_temp(form: FlaskForm, tmp_dir: str, ticket: str) -> str:
    src_path = path.join(tmp_dir, 'src', ticket)
    mkdir(src_path)
    filename = secure_filename(form.resource.data.filename)
    src_file = path.join(src_path, filename)
    form.resource.data.save(src_file)
    return src_file


def get_temp_dir():
    """Return the temporary directory"""
    return getenv('TEMPDIR') or gettempdir()


def check_directory_writable(d):
    fd, file_name = mkstemp(None, None, d)
    os.unlink(file_name)


def get_resized_report(gdf, form: FlaskForm, geo_type: str):
    ratio = None
    width = 1920
    height = None
    if form.aspect_ratio.data:
        ratio = form.aspect_ratio.data
    if form.width.data:
        width = form.width.data
    if form.height.data:
        height = form.height.data
    if geo_type == 'vector':
        report = gdf.profiler.report(basemap_provider=form.basemap_provider.data, basemap_name=form.basemap_name.data,
                                     aspect_ratio=ratio, width=width, height=height)
    else:
        report = gdf.report(basemap_provider=form.basemap_provider.data, basemap_name=form.basemap_name.data,
                            aspect_ratio=ratio, width=width, height=height)
    return report


def get_delimiter(ds_path: str):
    """ Returns the delimiter of the csv file """
    if ds_path.split('.')[-1] != 'csv':
        return None
    with open(ds_path) as f:
        first_line = f.readline()
        s = csv.Sniffer()
        return str(s.sniff(first_line).delimiter)


def get_ds(src_path: str, form: FlaskForm, geo_type: str, arrow_output_path=None):
    try:
        if geo_type == 'vector' or geo_type == 'netcdf':
            crs = 'WGS 84'
            if form.crs.data:
                crs = form.crs.data
            if geo_type == 'vector':
                lat_attr = None
                lon_attr = None
                if form.lat.data:
                    lat_attr = form.lat.data
                if form.lon.data:
                    lon_attr = form.lon.data
                return bdv.io.read_file(src_path, lat=lat_attr, lon=lon_attr, crs=crs, delimiter=get_delimiter(src_path),
                                        geom=form.geometry.data, output_path=arrow_output_path)
            elif geo_type == 'netcdf':
                lat_attr = 'lat'
                lon_attr = 'lon'
                time_attr = 'time'
                if form.lat.data:
                    lat_attr = form.lat.data
                if form.lon.data:
                    lon_attr = form.lon.data
                if form.time.data:
                    time_attr = form.time.data
                return bdv.io.read_file(src_path, type='netcdf', lat=lat_attr, lon=lon_attr, time=time_attr, crs=crs)
        elif geo_type == 'raster':
            return RasterData.from_file(src_path)
    except FileNotFoundError:
        abort(400, 'File not found')
