import tarfile
import zipfile
import os
from hashlib import md5
from tempfile import gettempdir, mkstemp
from uuid import uuid4
from os import path, makedirs, getenv
from flask import abort
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename


def validate_form(form: FlaskForm, logger) -> None:
    if not form.validate_on_submit():
        logger.error(f'Error while parsing input parameters: {str(form.errors)}')
        abort(400, form.errors)


def create_ticket() -> str:
    ticket = md5(str(uuid4()).encode()).hexdigest()
    return ticket


def get_subdirectories(folder_path: str) -> list:
    subdirectories = []
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
