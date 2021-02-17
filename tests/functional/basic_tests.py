import json
from os import path, getenv, mkdir
from io import StringIO
import logging
import tempfile
import pandas as pd

from geoprofile.app import app

# Setup/Teardown
from geoprofile.normalize.normalization_functions import date_normalization, phone_normalization, \
    alphabetical_normalization, special_character_normalization, case_normalization, transliteration

_tempdir: str = ""


def setup_module():
    print(f" == Setting up tests for {__name__}")
    app.config['TESTING'] = True
    
    global _tempdir
    _tempdir = getenv('TEMPDIR')
    if _tempdir:
        try:
            mkdir(_tempdir)
        except FileExistsError:
            pass
    else:
        _tempdir = tempfile.gettempdir()


def teardown_module():
    print(f" == Tearing down tests for {__name__}")


dirname = path.dirname(__file__)
netcdf_sample_path = path.join(dirname, '..', 'test_data/sresa1b_ncar_ccsm3-example.nc')
raster_sample_path = path.join(dirname, '..', 'test_data/S2A_MSIL1C_20170102T111442_N0204_R137_T30TXT_20170102T111441_'
                                              'TCI_cloudoptimized_512.tif')
vector_sample_path = path.join(dirname, '..', 'test_data/nyc_roads.zip')
corfu_shp_path = path.join(dirname, '..', 'test_data/get_pois_v02_corfu_2100.zip')
hotel_shp_path = path.join(dirname, '..', 'test_data/MR_TT_Hotel_THA.zip')
corfu_csv_path = path.join(dirname, '..', 'test_data/osm20_pois_corfu.csv')


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
        r = json.loads(res.get_data(as_text=True))
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
    data = {'resource': (open(netcdf_sample_path, 'rb'), 'sample_netcdf.nc')}
    path_to_test = '/profile/file/netcdf'
    expected_fields = {'assetType', 'metadata', 'dimensionsSize', 'dimensionsList', 'dimensionsProperties',
                       'variablesSize', 'variablesList', 'variablesProperties', 'mbr', 'temporalExtent',
                       'noDataValues', 'statistics'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_netcdf_file_input_deferred():
    data = {'resource': (open(netcdf_sample_path, 'rb'), 'sample_netcdf.nc'), 'response': 'deferred'}
    path_to_test = '/profile/file/netcdf'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_raster_file_input_prompt():
    data = {'resource': (open(raster_sample_path, 'rb'), 'sample_512.tif')}
    path_to_test = '/profile/file/raster'
    expected_fields = {'assetType', 'info', 'statistics', 'histogram', 'mbr', 'resolution', 'cog', 'numberOfBands',
                       'datatypes', 'noDataValue', 'crs', 'colorInterpretation'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_raster_file_input_deferred():
    data = {'resource': (open(raster_sample_path, 'rb'), 'sample_512.tif'), 'response': 'deferred'}
    path_to_test = '/profile/file/raster'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_vector_file_input_prompt():
    data = {'resource': (open(vector_sample_path, 'rb'), 'nyc_roads.zip')}
    path_to_test = '/profile/file/vector'
    expected_fields = {'attributes', 'clusters', 'clustersStatic', 'convexHull', 'count', 'crs', 'datatypes',
                       'distinct', 'distribution', 'featureCount', 'heatmap', 'heatmapStatic', 'mbr', 'quantiles',
                       'recurring', 'statistics', 'thumbnail'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_vector_file_input_deferred():
    data = {'resource': (open(vector_sample_path, 'rb'), 'nyc_roads.zip'), 'response': 'deferred'}
    path_to_test = '/profile/file/vector'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)


def test_profile_netcdf_path_input_prompt():
    data = {'resource': netcdf_sample_path}
    path_to_test = '/profile/path/netcdf'
    expected_fields = {'assetType', 'metadata', 'dimensionsSize', 'dimensionsList', 'dimensionsProperties',
                       'variablesSize', 'variablesList', 'variablesProperties', 'mbr', 'temporalExtent',
                       'noDataValues', 'statistics'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_netcdf_path_input_deferred():
    data = {'resource': netcdf_sample_path, 'response': 'deferred'}
    path_to_test = '/profile/path/netcdf'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_raster_path_input_prompt():
    data = {'resource': raster_sample_path}
    path_to_test = '/profile/path/raster'
    expected_fields = {'assetType', 'info', 'statistics', 'histogram', 'mbr', 'resolution', 'cog', 'numberOfBands',
                       'datatypes', 'noDataValue', 'crs', 'colorInterpretation'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_profile_raster_path_input_deferred():
    data = {'resource': raster_sample_path, 'response': 'deferred'}
    path_to_test = '/profile/path/raster'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


# def test_profile_vector_path_input_prompt():
#     data = {'resource':  vector_sample_path}
#     path_to_test = '/profile/path/vector'
#     expected_fields = {'attributes', 'clusters', 'clustersStatic', 'convexHull', 'count', 'crs', 'datatypes',
#                        'distinct', 'distribution', 'featureCount', 'heatmap', 'heatmapStatic', 'mbr', 'quantiles',
#                        'recurring', 'statistics', 'thumbnail'}
#     _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')
#
#
# def test_profile_vector_path_input_deferred():
#     data = {'resource': vector_sample_path, 'response': 'deferred'}
#     path_to_test = '/profile/path/vector'
#     expected_fields = {'endpoint', 'status', 'ticket'}
#     _check_endpoint(path_to_test, data, expected_fields, content_type='application/x-www-form-urlencoded')


def test_get_health_check():
    with app.test_client() as client:
        res = client.get('/_health', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        if 'reason' in r:
            logging.error('The service is unhealthy: %(reason)s\n%(detail)s', r)
        logging.debug("From /_health: %s" % r)
        assert r['status'] == 'OK'


def test_normalization_functions():
    # Date tests
    d: str = "19-09-2015"
    tf: str = "%Y/%m/%d"
    exp_res: str = "2015/09/19"
    res = date_normalization(d, tf)
    assert res == exp_res
    d: str = "11/11/2015"
    tf: str = "%Y %m %d"
    exp_res: str = "2015 11 11"
    res = date_normalization(d, tf)
    assert res == exp_res
    # Phone tests
    p: str = "+123-44 5678 999"
    exp_res: str = "123445678999"
    res = phone_normalization(p)
    assert res == exp_res
    p: str = "+123-44 5678 999"
    exp_res: str = "00123445678999"
    e: str = "00"
    res = phone_normalization(p, e)
    assert res == exp_res
    # Alphabetical
    lit: str = "I am fagi"
    exp_res: str = "am fagi I"
    res: str = alphabetical_normalization(lit)
    assert res == exp_res
    # Special Characters
    lit: str = "-_/@ contain m@any special characTers-"
    exp_res: str = " contain m any special characTers "
    res: str = special_character_normalization(lit)
    assert res == exp_res
    # case
    lit: str = "FaGi"
    exp_res: str = "fagi"
    res: str = case_normalization(lit)
    assert res == exp_res
    lit: str = "Ελληνική Δημοκρατία"
    exp_res: str = "Elliniki Dimokratia"
    res: str = transliteration(lit, 'el')
    assert res == exp_res


def test_normalize_transliterate_csv_file_input_prompt():
    payload = {'resource_type': 'csv', "transliteration-0": 'name',
               'transliteration_lang': 'el', 'resource': (open(corfu_csv_path, 'rb'), 'sample.csv')}
    path_to_test = '/normalize/file'
    with app.test_client() as client:
        res = client.post(path_to_test, data=payload, content_type='multipart/form-data')
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        expected = ['Naos Agion Theodoron', 'Άgios Arsenios', 'Naos U. Th. Odigitrias']
        df = pd.read_csv(StringIO(res.get_data(as_text=True)), sep=",")
        assert list(reversed(list(df['name'])))[1:4] == expected


def test_normalize_csv_file_input_deferred():
    data = {'resource': (open(corfu_csv_path, 'rb'), 'sample.csv'), 'response': 'deferred', 'resource_type': 'csv'}
    path_to_test = '/normalize/file'
    expected_fields = {'endpoint', 'status', 'ticket'}
    _check_endpoint(path_to_test, data, expected_fields)
