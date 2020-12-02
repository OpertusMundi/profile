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


def _check_all_fields_are_present(expected, r, api_path):
    """Check that all expected fields are present in a JSON response object (only examines top-level fields)"""
    missing = expected.difference(r.keys())
    if missing:
        logging.error(f'{api_path}: the response contained the fields {list(r.keys())} '
                      f' but it was missing the following fields: {missing}')
        assert False, 'The response is missing some fields'

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
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type='multipart/form-data')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'dimensions_list', 'dimensions_properties', 'dimensions_size', 'mbr', 'metadata',
                           'no_data_values', 'statistics', 'temporal_extent', 'variables_list', 'variables_properties',
                           'variables_size'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_netcdf_file_input_deferred():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc')}
    path_to_test = '/profile/file/netcdf'
    with app.test_client() as client:
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post(path_to_test, data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_raster_file_input_prompt():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_512.tif')}
    path_to_test = '/profile/file/raster'
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type='multipart/form-data')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                           'number_of_bands', 'resolution', 'statistics'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_raster_file_input_deferred():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_512.tif')}
    path_to_test = '/profile/file/raster'
    with app.test_client() as client:
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post(path_to_test, data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)

# def test_profile_vector_file_input():
#     url = 'https://download.geofabrik.de/europe/great-britain/wales-latest-free.shp.zip'
#     tmp_file_path = os.path.join(_tempdir, 'wales-latest-free.shp.zip')
#     urllib.request.urlretrieve(url, tmp_file_path)
#     data = {'resource': (open(tmp_file_path, 'rb'), 'wales-latest-free.shp.zip')}
#     path_to_test = '/profile/file/vector' 
#     with app.test_client() as client:
#         res = client.post(path_to_test, content_type='multipart/form-data')
#         assert res.status_code == 400
#         res = client.post(path_to_test, data=data, content_type='multipart/form-data')
#         assert res.status_code in [200, 202]
#         r = res.get_json()
#         expected_fields = {'statistics', 'distribution', 'quantiles', 'recurring', 'distinct', 'datatypes', 'thumbnail',
#                            'attributes', 'convex_hull', 'crs', 'featureCount', 'mbr', 'count'}
#        _check_all_fields_are_present(expected_fields, r, path_to_test);
#     os.remove(tmp_file_path)


def test_profile_netcdf_path_input_prompt():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/netcdf'
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type='application/x-www-form-urlencoded')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'dimensions_list', 'dimensions_properties', 'dimensions_size', 'mbr', 'metadata',
                           'no_data_values', 'statistics', 'temporal_extent', 'variables_list', 'variables_properties',
                           'variables_size'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_netcdf_path_input_deferred():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/netcdf'
    with app.test_client() as client:
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post(path_to_test, data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_raster_path_input_prompt():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/raster'
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type='application/x-www-form-urlencoded')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                           'number_of_bands', 'resolution', 'statistics'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)


def test_profile_raster_path_input_deferred():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    path_to_test = '/profile/path/raster'
    with app.test_client() as client:
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post(path_to_test, data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        _check_all_fields_are_present(expected_fields, r, path_to_test)
