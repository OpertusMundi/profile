import os
import urllib.request
import logging
import tempfile

from geoprofile.app import app

# Setup/Teardown

_tempdir: str = ""


def setup_module():
    print(f" == Setting up tests for {__name__}")
    app.config['TESTING'] = True
    
    global _tempdir
    _tempdir = os.getenv('TEMPDIR')
    if _tempdir:
        try:
            os.mkdir(_tempdir)
        except FileExistsError:
            pass
    else:
        _tempdir = tempfile.gettempdir()


def teardown_module():
    print(f" == Tearing down tests for {__name__}")
    pass


def _check_all_fields_are_present(expected: set, r: dict, api_path: str):
    """Check that all expected fields are present in a JSON response object (only examines top-level fields)"""
    missing = expected.difference(r.keys())
    if missing:
        logging.error(f'{api_path}: the response contained the fields {list(r.keys())} '
                      f' but it was missing the following fields: {missing}')
        assert False, 'The response is missing some fields'


def _check_endpoint(path_to_test: str, data: dict, expected_fields: set, content_type: str = 'multipart/form-data'):
    """Check an endpoint of the profile microservice"""
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type=content_type)
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type=content_type)
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        _check_all_fields_are_present(expected_fields, r, path_to_test)

#
# Tests
#


def test_get_documentation_1():
    with app.test_client() as client:
        res = client.get('/', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        assert not (r.get('openapi') is None)


def test_profile_netcdf_file_input_prompt():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc')}
    path_to_test = '/profile/file/netcdf'
    expected_fields = {'dimensions_list', 'dimensions_properties', 'dimensions_size', 'mbr', 'metadata',
                       'no_data_values', 'statistics', 'temporal_extent', 'variables_list', 'variables_properties',
                       'variables_size'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_netcdf_file_input_deferred():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc'), 'response': 'deferred'}
    path_to_test = '/profile/file/netcdf'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_raster_file_input_prompt():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_512.tif')}
    path_to_test = '/profile/file/raster'
    expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                       'number_of_bands', 'resolution', 'statistics'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_raster_file_input_deferred():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_512.tif'), 'response': 'deferred'}
    path_to_test = '/profile/file/raster'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_netcdf_path_input_prompt():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/netcdf'
    expected_fields = {'dimensions_list', 'dimensions_properties', 'dimensions_size', 'mbr', 'metadata',
                       'no_data_values', 'statistics', 'temporal_extent', 'variables_list', 'variables_properties',
                       'variables_size'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_netcdf_path_input_deferred():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path, 'response': 'deferred'}
    path_to_test = '/profile/path/netcdf'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_raster_path_input_prompt():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/raster'
    expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                       'number_of_bands', 'resolution', 'statistics'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_raster_path_input_deferred():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path, 'response': 'deferred'}
    path_to_test = '/profile/path/raster'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_get_health_check():
    with app.test_client() as client:
        res = client.get('/_health', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        if 'reason' in r:
            logging.error('The service is unhealthy: %(reason)s\n%(detail)s', r)
        logging.debug("From /_health: %s" % r)
        assert r['status'] == 'OK'
