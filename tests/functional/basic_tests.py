import os
import urllib.request
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

# Tests


def test_get_documentation_1():
    with app.test_client() as client:
        res = client.get('/', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        assert not (r.get('openapi') is None)


def test_profile_netcdf_file_input():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc')}
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post('/profile/file/netcdf', content_type='multipart/form-data')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post('/profile/file/netcdf', data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'mbr', 'metadata', 'variables_list', 'dimensions_size', 'temporal_extent', 'dimensions_list',
                           'variables_properties', 'no_data_values', 'statistics', 'variables_size', 'sample',
                           'dimensions_properties'}
        assert set(r.keys()) == expected_fields
        data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc'), 'response': 'deferred'}
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post('/profile/file/netcdf', data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        assert set(r.keys()) == expected_fields
    os.remove(tmp_file_path)


def test_profile_raster_file_input():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': (open(tmp_file_path, 'rb'), 'sample_512.tif')}
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post('/profile/file/raster', content_type='multipart/form-data')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post('/profile/file/raster', data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                           'number_of_bands', 'resolution', 'statistics'}
        assert set(r.keys()) == expected_fields
        data = {'resource': (open(tmp_file_path, 'rb'), 'sample_netcdf.nc'), 'response': 'deferred'}
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post('/profile/file/raster', data=data, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        assert set(r.keys()) == expected_fields
    os.remove(tmp_file_path)


# def test_profile_vector_file_input():
#     url = 'https://download.geofabrik.de/europe/great-britain/wales-latest-free.shp.zip'
#     tmp_file_path = os.path.join(_tempdir, 'wales-latest-free.shp.zip')
#     urllib.request.urlretrieve(url, tmp_file_path)
#     data = {'resource': (open(tmp_file_path, 'rb'), 'wales-latest-free.shp.zip')}
#     with app.test_client() as client:
#         res = client.post('/profile/file/vector', content_type='multipart/form-data')
#         assert res.status_code == 400
#         res = client.post('/profile/file/vector', data=data, content_type='multipart/form-data')
#         assert res.status_code in [200, 202]
#         r = res.get_json()
#         expected_fields = {'statistics', 'distribution', 'quantiles', 'recurring', 'distinct', 'datatypes', 'thumbnail',
#                            'attributes', 'convex_hull', 'crs', 'featureCount', 'mbr', 'count'}
#         assert set(r.keys()) == expected_fields
#     os.remove(tmp_file_path)


def test_profile_netcdf_path_input():
    url = 'https://www.unidata.ucar.edu/software/netcdf/examples/test_echam_spectral-deflated.nc'
    tmp_file_path = os.path.join(_tempdir, 'sample_netcdf.nc')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post('/profile/path/netcdf', content_type='application/x-www-form-urlencoded')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post('/profile/path/netcdf', data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'mbr', 'metadata', 'variables_list', 'dimensions_size', 'temporal_extent', 'dimensions_list',
                           'variables_properties', 'no_data_values', 'statistics', 'variables_size', 'sample',
                           'dimensions_properties'}
        assert set(r.keys()) == expected_fields
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post('/profile/path/netcdf', data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        assert set(r.keys()) == expected_fields
    os.remove(tmp_file_path)


def test_profile_raster_path_input():
    url = 'http://even.rouault.free.fr' \
          '/gtiff_test/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_TCI_cloudoptimized_512.tif'
    tmp_file_path = os.path.join(_tempdir, 'sample_512.tif')
    urllib.request.urlretrieve(url, tmp_file_path)
    data = {'resource': tmp_file_path}
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post('/profile/path/raster', content_type='application/x-www-form-urlencoded')
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post('/profile/path/raster', data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r1 = res.get_json()
        expected_fields = {'cog', 'color_interpetation', 'crs', 'datatypes', 'histogram', 'info', 'mbr', 'noDataValue',
                           'number_of_bands', 'resolution', 'statistics'}
        assert set(r1.keys()) == expected_fields
        data['response'] = 'deferred'
        # Test if it succeeds when a file is submitted with deferred processing
        res = client.post('/profile/path/raster', data=data, content_type='application/x-www-form-urlencoded')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r2 = res.get_json()
        expected_fields = {'endpoint', 'status', 'ticket'}
        assert set(r2.keys()) == expected_fields
        os.remove(tmp_file_path)
