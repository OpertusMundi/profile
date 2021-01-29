from datetime import datetime, timezone
import json
from flask import Flask
from apispec import APISpec
from apispec_webframeworks.flask import FlaskPlugin
from os import path, getenv, stat
from flask_cors import CORS
from flask_executor import Executor
from flask import make_response, send_file
from flask_wtf import FlaskForm

from . import db
from .forms import ProfileFileForm, ProfilePathForm
from .logging import getLoggers
from .utils import create_ticket, get_tmp_dir, mkdir, validate_form, save_to_temp, check_directory_writable, \
    get_temp_dir, get_resized_report, get_ds, uncompress_file


class OutputDirNotSet(Exception):
    pass


if getenv('OUTPUT_DIR') is None:
    raise OutputDirNotSet('Environment variable OUTPUT_DIR is not set.')

# Logging
mainLogger, accountLogger = getLoggers()

# OpenAPI documentation
spec = APISpec(
    title="Profile API",
    version=getenv('VERSION'),
    info=dict(
        description="A service that profiles geospatial data using the BigDataVoyant library "
                    "https://github.com/OpertusMundi/BigDataVoyant",
        contact={"email": "kpsarakis94@gmail.com"}
    ),
    externalDocs={"description": "GitHub", "url": "https://github.com/OpertusMundi/profile"},
    openapi_version="3.0.2",
    plugins=[FlaskPlugin()],
)

# Initialize app
app = Flask(__name__, instance_relative_config=True, instance_path=getenv('INSTANCE_PATH'))
app.config.from_mapping(
    SECRET_KEY=getenv('SECRET_KEY'),
    DATABASE=getenv('DATABASE'),
)


def executor_callback(future):
    """The callback function called when a job has completed."""
    ticket, result, success, comment = future.result()
    if result is not None:
        rel_path = datetime.now().strftime("%y%m%d")
        rel_path = path.join(rel_path, ticket)
        mkdir(path.join(getenv('OUTPUT_DIR'), rel_path))
        filepath = path.join(getenv('OUTPUT_DIR'), rel_path, "result.json")
        result.to_file(filepath)
    else:
        filepath = None
    with app.app_context():
        dbc = db.get_db()
        db_result = dbc.execute('SELECT requested_time, filesize FROM tickets WHERE ticket = ?;', [ticket]).fetchone()
        time = db_result['requested_time']
        filesize = db_result['filesize']
        execution_time = round((datetime.now(timezone.utc) - time.replace(tzinfo=timezone.utc)).total_seconds(), 3)
        dbc.execute('UPDATE tickets SET result=?, success=?, status=1, execution_time=?, comment=? WHERE ticket=?;',
                    [filepath, success, execution_time, comment, ticket])
        dbc.commit()
        accountLogger(ticket=ticket, success=success, execution_start=time, execution_time=execution_time,
                      comment=comment, filesize=filesize)
        dbc.close()


# Ensure the instance folder exists and initialize application, db and executor.
mkdir(app.instance_path)
db.init_app(app)
executor = Executor(app)
executor.add_default_done_callback(executor_callback)

# Enable CORS
if getenv('CORS') is not None:
    if getenv('CORS')[0:1] == '[':
        origins = json.loads(getenv('CORS'))
    else:
        origins = getenv('CORS')
    cors = CORS(app, origins=origins)


@executor.job
def enqueue(ticket: str, src_path: str, file_type: str, form: FlaskForm) -> tuple:
    """Enqueue a profile job (in case requested response type is 'deferred')."""
    try:
        result = {}
        if file_type == 'netcdf':
            ds = get_ds(src_path, form, 'netcdf')
            result = get_resized_report(ds, form, 'netcdf')
        elif file_type == 'raster':
            ds = get_ds(src_path, form, 'raster')
            result = get_resized_report(ds, form, 'raster')
        elif file_type == 'vector':
            ds = get_ds(src_path, form, 'vector')
            result = get_resized_report(ds, form, 'vector')
    except Exception as e:
        return ticket, None, 0, str(e)
    else:
        return ticket, result, 1, None
    finally:
        filesize = stat(src_path).st_size
        dbc = db.get_db()
        dbc.execute('INSERT INTO tickets (ticket, filesize) VALUES(?, ?);', [ticket, filesize])
        dbc.commit()
        dbc.close()


@app.route("/")
def index():
    """The index route, gives info about the API endpoints."""
    mainLogger.info('Generating OpenAPI document...')
    return make_response(spec.to_dict(), 200)


@app.route("/_health")
def health_check():
    """Perform basic health checks
    ---
    get:
      tags:
      - Health
      summary: Get health status
      description: 'Get health status'
      operationId: 'getHealth'
      responses:
        default:
          description: An object with status information
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: A status of 'OK' or 'FAILED'
                  reason:
                    type: string
                    description: the reason of failure (if failed)
                  detail:
                    type: string
                    description: more details on this failure (if failed)
              examples:
                example-1:
                  value: |-
                    {"status": "OK"}
    """
    mainLogger.info('Performing health checks...')
    # Check that temp directory is writable
    try:
        check_directory_writable(get_temp_dir())
    except Exception as exc:
        return make_response({'status': 'FAILED', 'reason': 'temp directory not writable', 'detail': str(exc)},
                             200)
    # Check that we can connect to our PostGIS backend
    try:
        dbc = db.get_db()
        dbc.execute('SELECT 1').fetchone()
    except Exception as exc:
        return make_response({'status': 'FAILED', 'reason': 'cannot connect to SQLite backend', 'detail': str(exc)},
                             200)
    # Check that we can connect to our Geoserver backend
    # Todo ...
    return make_response({'status': 'OK'},
                         200)


@app.route("/profile/file/netcdf", methods=["POST"])
def profile_file_netcdf():
    """Profile a NetCDF file that is provided with the request
        ---
        post:
          summary: Profile a NetCDF file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              multipart/form-data:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    basemap_provider:
                      type: string
                      default: OpenStreetMap
                      description: The basemap provider
                    basemap_name:
                      type: string
                      default: Mapnik
                      description: The name of the basemap
                    aspect_ratio:
                      type: float
                      description: The aspect ratio of the static map to be generated
                    width:
                      type: integer
                      description: The width (in pixels) of the static map to be generated
                    height:
                      type: integer
                      description: The height (in pixels) of the static map to be generated
                    lat:
                      type: string
                      description: The column name with the latitude information
                    lon:
                      type: string
                      description: The column name with the longitude information
                    time:
                      type: string
                      description: The column name with the time information
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: The type of the asset (always *netCDF*).
                        metadata:
                          type: object
                          description: File's metadata
                        dimensionsSize:
                          type: integer
                          description: Number of dimensions.
                        dimensionsList:
                          type: object
                          description: List of dimensions.
                        dimensionsProperties:
                          type: object
                          description: The properties for each dimension.
                        variablesSize:
                          type: integer
                          description: Number of variables.
                        variablesList:
                          type: object
                          description: List of variables.
                        variablesProperties:
                          type: object
                          description: The properties for each variable.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        temporalExtent:
                          type: string
                          description: A string representing the temporal extend of the dataset.
                        noDataValues:
                          type: object
                          description: The no-data value for each the variables.
                        statistics:
                          type: object
                          description: General statistics for each of the variables (*missing*, *min*, *max*, *mean*, *std*, *variance* and whether the data are *contiguous*).
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfileFileForm()
    validate_form(form, mainLogger)

    tmp_dir: str = get_tmp_dir("profile")
    ticket: str = create_ticket()
    src_file_path: str = save_to_temp(form, tmp_dir, ticket)

    # Immediate results
    if form.response.data == "prompt":
        ds = get_ds(src_file_path, form, 'netcdf')
        report = get_resized_report(ds, form, 'netcdf')
        return make_response(report, 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="netcdf", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/profile/file/raster", methods=["POST"])
def profile_file_raster():
    """Profile a raster file that is provided with the request
        ---
        post:
          summary: Profile a raster file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              multipart/form-data:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: The type of the asset (always *raster*).
                        info:
                          type: object
                          description: A JSON with general information about the raster file (such as metadata, image structure, etc.).
                        statistics:
                          type: object
                          description: A list with the statistics for each band of the raster file.
                        histogram:
                          type: object
                          description: The default histogram of the raster file for each band.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        resolution:
                          type: object
                          description: The resolution for each dimension, and the unit of measurement.
                        cog:
                          type: boolean
                          description: If raster is GeoTiff, whether it is Cloud-Optimized or not.
                        numberOfBands:
                          type: integer
                          description: The number of bands in the raster.
                        datatypes:
                          type: object
                          description: The data type for each band.
                        noDataValue:
                          type: object
                          description: The no-data value for each band.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                        colorInterpretation:
                          type: object
                          description: The Color Interpretation for each band.
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfileFileForm()
    validate_form(form, mainLogger)

    tmp_dir: str = get_tmp_dir("profile")
    ticket: str = create_ticket()
    src_file_path: str = save_to_temp(form, tmp_dir, ticket)

    # Wait for results
    if form.response.data == "prompt":
        ds = get_ds(src_file_path, form, 'raster')
        report = get_resized_report(ds, form, 'raster')
        return make_response(report, 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="raster", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/profile/file/vector", methods=["POST"])
def profile_file_vector():
    """Profile a vector file that is provided with the request
        ---
        post:
          summary: Profile a vector file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              multipart/form-data:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    basemap_provider:
                      type: string
                      default: OpenStreetMap
                      description: The basemap provider
                    basemap_name:
                      type: string
                      default: Mapnik
                      description: The name of the basemap
                    aspect_ratio:
                      type: float
                      description: The aspect ratio of the static map to be generated
                    width:
                      type: integer
                      description: The width (in pixels) of the static map to be generated
                    height:
                      type: integer
                      description: The height (in pixels) of the static map to be generated
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: One of *tabular* or *vector*.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        featureCount:
                          type: integer
                          description: The number of features in the dataset.
                        count:
                          type: object
                          description: Count not null values for each attribute in the dataset.
                        convexHull:
                          type: string
                          description: The Well-Known-Text representation of the Convex Hull for all geometries.
                        convexHullStatic:
                          type: string
                          description: A PNG static map showing the convex hull, base64 encoded.
                        thumbnail:
                          type: string
                          description: A PNG thumbnail of the dataset, base64 encoded.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                        attributes:
                          type: object
                          description: A list with the attributes of the dataset.
                        datatypes:
                          type: object
                          description: The datatypes for each of the dataset's attributes.
                        distribution:
                          type: object
                          description: The distribution of the values for each attribute in the dataset.
                        quantiles:
                          type: object
                          description: The 5, 25, 50, 75, 95 quantiles for each of the numeric attributes in the dataset.
                        distinct:
                          type: object
                          description: The distinct values for each of the attributes in the dataset.
                        recurring:
                          type: object
                          description: The most frequent values for each of the attributes in the dataset.
                        heatmap:
                          type: object
                          description: A GeoJSON with a heatmap of the geometries.
                        heatmapStatic:
                          type: string
                          description: A PNG static heatmap, base64 encoded.
                        clusters:
                          type: object
                          description: A GeoJSON with clustered geometries.
                        clustersStatic:
                          type: string
                          description: A PNG static map with the clustered geometries, base64 encoded.
                        statistics:
                          type: object
                          description: Statistics (*min*, *max*, *mean*, *median*, *std*, *sum*) for the numerical attributes in the dataset.
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfileFileForm()
    validate_form(form, mainLogger)

    tmp_dir: str = get_tmp_dir("profile")
    ticket: str = create_ticket()
    src_file_path: str = save_to_temp(form, tmp_dir, ticket)

    # Wait for results
    if form.response.data == "prompt":
        src_file_path = uncompress_file(src_file_path)
        ds = get_ds(src_file_path, form, 'vector')
        report = get_resized_report(ds, form, 'vector')
        return make_response(report, 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/profile/path/netcdf", methods=["POST"])
def profile_path_netcdf():
    """Profile a NetCDF file that its path provided with the request
        ---
        post:
          summary: Profile a NetCDF file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              application/x-www-form-urlencoded:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    basemap_provider:
                      type: string
                      default: OpenStreetMap
                      description: The basemap provider
                    basemap_name:
                      type: string
                      default: Mapnik
                      description: The name of the basemap
                    aspect_ratio:
                      type: float
                      description: The aspect ratio of the static map to be generated
                    width:
                      type: integer
                      description: The width (in pixels) of the static map to be generated
                    height:
                      type: integer
                      description: The height (in pixels) of the static map to be generated
                    lat:
                      type: string
                      description: The column name with the latitude information
                    lon:
                      type: string
                      description: The column name with the longitude information
                    time:
                      type: string
                      description: The column name with the time information
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: The type of the asset (always *netCDF*).
                        metadata:
                          type: object
                          description: File's metadata
                        dimensionsSize:
                          type: integer
                          description: Number of dimensions.
                        dimensionsList:
                          type: object
                          description: List of dimensions.
                        dimensionsProperties:
                          type: object
                          description: The properties for each dimension.
                        variablesSize:
                          type: integer
                          description: Number of variables.
                        variablesList:
                          type: object
                          description: List of variables.
                        variablesProperties:
                          type: object
                          description: The properties for each variable.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        temporalExtent:
                          type: string
                          description: A string representing the temporal extend of the dataset.
                        noDataValues:
                          type: object
                          description: The no-data value for each the variables.
                        statistics:
                          type: object
                          description: General statistics for each of the variables (*missing*, *min*, *max*, *mean*, *std*, *variance* and whether the data are *contiguous*).
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfilePathForm()
    validate_form(form, mainLogger)

    src_file_path: str = form.resource.data

    # Immediate results
    if form.response.data == "prompt":
        ds = get_ds(src_file_path, form, 'netcdf')
        report = get_resized_report(ds, form, 'netcdf')
        return make_response(report, 200)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="netcdf", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/profile/path/raster", methods=["POST"])
def profile_path_raster():
    """Profile a raster that its path provided with the request
        ---
        post:
          summary: Profile a raster file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              application/x-www-form-urlencoded:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: The type of the asset (always *raster*).
                        info:
                          type: object
                          description: A JSON with general information about the raster file (such as metadata, image structure, etc.).
                        statistics:
                          type: object
                          description: A list with the statistics for each band of the raster file.
                        histogram:
                          type: object
                          description: The default histogram of the raster file for each band.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        resolution:
                          type: object
                          description: The resolution for each dimension, and the unit of measurement.
                        cog:
                          type: boolean
                          description: If raster is GeoTiff, whether it is Cloud-Optimized or not.
                        numberOfBands:
                          type: integer
                          description: The number of bands in the raster.
                        datatypes:
                          type: object
                          description: The data type for each band.
                        noDataValue:
                          type: object
                          description: The no-data value for each band.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                        colorInterpretation:
                          type: object
                          description: The Color Interpretation for each band.
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfilePathForm()
    validate_form(form, mainLogger)

    src_file_path: str = form.resource.data

    # Wait for results
    if form.response.data == "prompt":
        ds = get_ds(src_file_path, form, 'raster')
        report = get_resized_report(ds, form, 'raster')
        return make_response(report, 200)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="raster", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/profile/path/vector", methods=["POST"])
def profile_path_vector():
    """Profile a vector that its path provided with the request
        ---
        post:
          summary: Profile a vector file that is provided with the request
          tags:
            - Profile
          requestBody:
            required: true
            content:
              application/x-www-form-urlencoded:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      format: binary
                      description: The spatial file.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    basemap_provider:
                      type: string
                      default: OpenStreetMap
                      description: The basemap provider
                    basemap_name:
                      type: string
                      default: Mapnik
                      description: The name of the basemap
                    aspect_ratio:
                      type: float
                      description: The aspect ratio of the static map to be generated
                    width:
                      type: integer
                      description: The width (in pixels) of the static map to be generated
                    height:
                      type: integer
                      description: The height (in pixels) of the static map to be generated
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        assetType:
                          type: string
                          description: One of *tabular* or *vector*.
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        featureCount:
                          type: integer
                          description: The number of features in the dataset.
                        count:
                          type: object
                          description: Count not null values for each attribute in the dataset.
                        convexHull:
                          type: string
                          description: The Well-Known-Text representation of the Convex Hull for all geometries.
                        convexHullStatic:
                          type: string
                          description: A PNG static map showing the convex hull, base64 encoded.
                        thumbnail:
                          type: string
                          description: A PNG thumbnail of the dataset, base64 encoded.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                        attributes:
                          type: object
                          description: A list with the attributes of the dataset.
                        datatypes:
                          type: object
                          description: The datatypes for each of the dataset's attributes.
                        distribution:
                          type: object
                          description: The distribution of the values for each attribute in the dataset.
                        quantiles:
                          type: object
                          description: The 5, 25, 50, 75, 95 quantiles for each of the numeric attributes in the dataset.
                        distinct:
                          type: object
                          description: The distinct values for each of the attributes in the dataset.
                        recurring:
                          type: object
                          description: The most frequent values for each of the attributes in the dataset.
                        heatmap:
                          type: object
                          description: A GeoJSON with a heatmap of the geometries.
                        heatmapStatic:
                          type: string
                          description: A PNG static heatmap, base64 encoded.
                        clusters:
                          type: object
                          description: A GeoJSON with clustered geometries.
                        clustersStatic:
                          type: string
                          description: A PNG static map with the clustered geometries, base64 encoded.
                        statistics:
                          type: object
                          description: Statistics (*min*, *max*, *mean*, *median*, *std*, *sum*) for the numerical attributes in the dataset.
            202:
              description: Accepted for processing, but profile has not been completed.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      ticket:
                        type: string
                        description: The ticket corresponding to the request.
                      endpoint:
                        type: string
                        description: The *resource* endpoint to get the resulting resource when ready.
                      status:
                        type: string
                        description: The *status* endpoint to poll for the status of the request.
              links:
                GetStatus:
                  operationId: getStatus
                  parameters:
                    ticket: '$response.body#/ticket'
                  description: The `ticket` value returned in the response can be used as the `ticket` parameter in `GET /status/{ticket}`.
            400:
              description: Client error.
    """
    form = ProfilePathForm()
    validate_form(form, mainLogger)

    src_file_path: str = form.resource.data

    # Wait for results
    if form.response.data == "prompt":
        src_file_path = uncompress_file(src_file_path)
        ds = get_ds(src_file_path, form, 'vector')
        report = get_resized_report(ds, form, 'vector')
        return make_response(report, 200)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/status/<ticket>")
def status(ticket):
    """Get the status of a specific ticket.
    ---
    get:
      summary: Get the status of a profile request.
      operationId: getStatus
      description: Returns the status of a request corresponding to a specific ticket.
      tags:
        - Status
      parameters:
        - name: ticket
          in: path
          description: The ticket of the request
          required: true
          schema:
            type: string
      responses:
        200:
          description: Ticket found and status returned.
          content:
            application/json:
              schema:
                type: object
                properties:
                  completed:
                    type: boolean
                    description: Whether profiling process has been completed or not.
                  success:
                    type: boolean
                    description: Whether profiling process completed successfully.
                  comment:
                    type: string
                    description: If profiling has failed, a short comment describing the reason.
                  requested:
                    type: string
                    format: datetime
                    description: The timestamp of the request.
                  execution_time(s):
                    type: integer
                    description: The execution time in seconds.
        404:
          description: Ticket not found.
    """
    if ticket is None:
        return make_response('Ticket is missing.', 400)
    dbc = db.get_db()
    results = dbc.execute(
        'SELECT status, success, requested_time, execution_time, comment FROM tickets WHERE ticket = ?',
        [ticket]).fetchone()
    if results is not None:
        if results['success'] is not None:
            success = bool(results['success'])
        else:
            success = None
        return make_response({"completed": bool(results['status']), "success": success,
                              "requested": results['requested_time'], "execution_time(s)": results['execution_time'],
                              "comment": results['comment']}, 200)
    return make_response('Not found.', 404)


@app.route("/resource/<ticket>")
def resource(ticket):
    """Get the resulted resource associated with a specific ticket.
    ---
    get:
      summary: Get the resource associated to a profile request.
      description: Returns the resource resulted from a profile request corresponding to a specific ticket.
      tags:
        - Resource
      parameters:
        - name: ticket
          in: path
          description: The ticket of the request
          required: true
          schema:
            type: string
      responses:
        200:
          description: The profiled compressed spatial file.
          content:
            application/x-tar:
              schema:
                type: string
                format: binary
        404:
          description: Ticket not found or profile has not been completed.
        507:
          description: Resource does not exist.
    """
    if ticket is None:
        return make_response('Resource ticket is missing.', 400)
    dbc = db.get_db()
    rel_path = dbc.execute('SELECT result FROM tickets WHERE ticket = ?', [ticket]).fetchone()['result']
    if rel_path is None:
        return make_response('Not found.', 404)
    file = path.join(getenv('OUTPUT_DIR'), rel_path)
    if not path.isfile(file):
        return make_response('Resource does not exist.', 507)
    return send_file(file, as_attachment=True)


# Views
with app.test_request_context():
    spec.path(view=profile_file_netcdf)
    spec.path(view=profile_file_raster)
    spec.path(view=profile_file_vector)
    spec.path(view=profile_path_netcdf)
    spec.path(view=profile_path_raster)
    spec.path(view=profile_path_vector)
    spec.path(view=status)
    spec.path(view=resource)
