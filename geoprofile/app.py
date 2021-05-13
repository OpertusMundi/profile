from datetime import datetime, timezone
import json
from enum import Enum, auto
from flask import Flask, abort, jsonify, after_this_request
from apispec import APISpec
from apispec_webframeworks.flask import FlaskPlugin
from os import path, getenv, stat
from flask_cors import CORS
from flask_executor import Executor
from flask import make_response, send_file
from flask_wtf import FlaskForm
import pandas as pd

from . import db
from .forms import ProfileFileForm, ProfilePathForm, NormalizeFileForm, NormalizePathForm, SummarizeFileForm, \
    SummarizePathForm
from .logging import getLoggers
from .normalize.utils import normalize_gdf, store_gdf
from .summarize.summarization import summarize
from .utils import create_ticket, get_tmp_dir, mkdir, validate_form, save_to_temp, check_directory_writable, \
    get_temp_dir, get_resized_report, get_ds, uncompress_file, delete_from_temp


class OutputDirNotSet(Exception):
    pass


FILE_NOT_FOUND_MESSAGE = "File not found"

if getenv('OUTPUT_DIR') is None:
    raise OutputDirNotSet('Environment variable OUTPUT_DIR is not set.')


PROFILE_TEMP_DIR: str = get_tmp_dir("profile")
NORMALIZE_TEMP_DIR: str = get_tmp_dir("normalize")
SUMMARIZE_TEMP_DIR: str = get_tmp_dir("summarize")

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
environment = getenv('FLASK_ENV')
if environment == 'testing' or environment == 'development':
    secret_key = environment
else:
    secret_key = getenv('SECRET_KEY') or open(getenv('SECRET_KEY_FILE')).read()
app.config.from_mapping(
    SECRET_KEY=secret_key,
    DATABASE=getenv('DATABASE'),
)


def executor_callback(future):
    """The callback function called when a job has completed."""
    ticket, result, job_type, success, comment = future.result()
    if result is not None:
        rel_path = datetime.now().strftime("%y%m%d")
        rel_path = path.join(rel_path, ticket)
        output_path: str = path.join(getenv('OUTPUT_DIR'), rel_path)
        mkdir(output_path)
        filepath = None
        if job_type is JobType.PROFILE:
            filepath = path.join(getenv('OUTPUT_DIR'), rel_path, "result.json")
            result.to_file(filepath)
        elif job_type is JobType.NORMALIZE:
            gdf, resource_type, file_name = result
            filepath = store_gdf(gdf, resource_type, file_name, output_path)
        elif job_type is JobType.SUMMARIZE:
            filepath = path.join(getenv('OUTPUT_DIR'), rel_path, "result.json")
            with open(filepath, 'w') as fp:
                json.dump(result, fp)
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
        if job_type is JobType.PROFILE:
            delete_from_temp(path.join(PROFILE_TEMP_DIR, ticket))
        elif job_type is JobType.NORMALIZE:
            delete_from_temp(path.join(NORMALIZE_TEMP_DIR, ticket))
        elif job_type is JobType.SUMMARIZE:
            delete_from_temp(path.join(SUMMARIZE_TEMP_DIR, ticket))
        mainLogger.info(f'Processing of ticket: {ticket} is completed successfully')


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


class JobType(Enum):
    NORMALIZE = auto()
    PROFILE = auto()
    SUMMARIZE = auto()


@executor.job
def enqueue(ticket: str, src_path: str, file_type: str, form: FlaskForm, job_type: JobType) -> tuple:
    """Enqueue a job (in case requested response type is 'deferred')."""
    filesize = stat(src_path).st_size
    dbc = db.get_db()
    dbc.execute('INSERT INTO tickets (ticket, filesize) VALUES(?, ?);', [ticket, filesize])
    dbc.commit()
    dbc.close()
    mainLogger.info(f'Starting processing ticket: {ticket}')
    try:
        result = None
        if job_type is JobType.PROFILE:
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
        elif job_type is JobType.NORMALIZE:
            gdf = get_ds(src_path, form, 'vector')
            gdf = normalize_gdf(form, gdf)
            file_name = path.split(src_path)[1].split('.')[0] + '_normalized'
            result = gdf, form.resource_type.data, file_name
        elif job_type is JobType.SUMMARIZE:
            gdf = get_ds(src_path, form, 'vector').to_geopandas_df()
            df = pd.DataFrame(gdf.drop(columns='geometry'))
            json_summary = summarize(df, form)
            result = json_summary
    except Exception as e:
        mainLogger.error(f'Processing of ticket: {ticket} failed')
        return ticket, None, 0, str(e)
    else:
        return ticket, result, job_type, 1, None


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
                    crs:
                      type: string
                      description: The dataset's crs
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
                          description: The type of the asset (always *NetCDF*).
                          example: NetCDF
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        metadata:
                          type: object
                          description: The metadata object as written in the file. The key is a free field for the data provider, usually describing the given information.
                          additionalProperties:
                            type: string
                        dimensionsSize:
                          type: integer
                          description: The number of the dimensions.
                          example: 4
                        dimensionsList:
                          type: array
                          description: A list with the dimensions.
                          items:
                            type: string
                            description: The dimension name.
                          example:
                            - lon
                            - lat
                            - level
                            - time
                        dimensionsProperties:
                          type: object
                          description: The properties of each dimension. The key is the dimension.
                          additionalProperties:
                            type: object
                            description: "The properties of the specific dimension. **Note**: below are only the common properties; other custom properties may also be present."
                            properties:
                              type:
                                type: string
                                description: The datatype of the dimension.
                                example: float64
                              size:
                                type: integer
                                description: The size of the dimension variable.
                                example: 128
                              long_name:
                                type: string
                                description: The long name of the dimension.
                                example: longitude
                              units:
                                type: string
                                description: A description of the dimension's units.
                                example: degrees_east
                        variablesSize:
                          type: integer
                          description: Number of variables.
                          example: 12
                        variablesList:
                          type: array
                          description: A list with the variables.
                          items:
                            type: string
                            description: The name of the variable.
                          example:
                            - temperature
                            - pm1.0
                            - pm2.5
                            - pm10
                        variablesProperties:
                          type: object
                          description: The properties for each variable. The key is the variable.
                          additionalProperties:
                            type: object
                            description: "The properties of the specific variable. **Note**: below are only the common properties; other custom properties may also be present."
                            properties:
                              dimensions:
                                type: array
                                description: A list of the dimensions that this variable depends on.
                                items:
                                  type: string
                                example:
                                  - lat
                                  - lon
                              type:
                                type: string
                                description: The datatype of the variable.
                                example: float64
                              size:
                                type: integer
                                description: The size of the variable.
                                example: 128
                              units:
                                type: string
                                description: A description of the variable's units.
                                example: degrees_east
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        temporalExtent:
                          type: string
                          description: A free-text string representing the temporal extend of the dataset.
                          example: 0.000000 - 720.000000 hours
                        noDataValues:
                          type: object
                          description: The no-data value for each the variables. The key is the variable.
                          additionalProperties:
                            type: numeric
                            description: The no-data value for the specific variable.
                        statistics:
                          type: object
                          description: Descriptive statistics for each of the variables. The key is the variable.
                          additionalProperties:
                            type: object
                            description: Descriptive statistics for the specific variable.
                            properties:
                              count:
                                type: integer
                                description: The number of values for the specific variable.
                                example: 220
                              missing:
                                type: integer
                                description: The number of missing values for the specific variable.
                                example: 0
                              min:
                                type: numeric
                                description: The minimum value of the specific variable.
                                example: 0.4
                              max:
                                type: numeric
                                description: The maximum value of the specific variable.
                                example: 20.6
                              mean:
                                type: numeric
                                description: The mean value of the specific variable.
                                example: 10.7
                              std:
                                type: numeric
                                description: The standard deviation for the specific variable.
                                example: 2.4
                              variance:
                                type: numeric
                                description: The variance of the specific variable.
                                example: 7.9
                              contiguous:
                                type: boolean
                                description: Whether the data are contiguous or not.
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
    mainLogger.info(f"Starting /profile/file/netcdf with file: {form.resource.data.filename}")
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir)
    src_file_path = uncompress_file(src_file_path)

    # Immediate results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'netcdf')
        report = get_resized_report(ds, form, 'netcdf')
        return make_response(report.to_json(), 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="netcdf", form=form, job_type=JobType.PROFILE)
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
                          example: raster
                        info:
                          type: object
                          description: General information about the raster file.
                          properties:
                            metadata:
                              type: object
                              description: Metadata of the the raster as written in the file. The keys are free-text.
                              additionalProperties:
                                type: string
                              example:
                                AREA_OR_POINT: Point
                                TIFFTAG_MAXSAMPLEVALUE: 254
                            imageStructure:
                              type: object
                              description: Various values describing the image structure. The keys depend on the raster.
                              additionalProperties:
                                type: string
                              example:
                                COMPRESSION: YCbCr JPEG
                                INTERLEAVE: PIXEL
                                SOURCE_COLOR_SPACE: YCbCr
                            driver:
                              type: string
                              description: The driver used to open the raster.
                              example: GeoTIFF
                            files:
                              type: array
                              description: A list of the files associated with the raster.
                              items:
                                type: string
                                description: Filename.
                              example:
                                - example.tif
                            width:
                              type: integer
                              description: The width in pixels.
                              example: 1920
                            height:
                              type: integer
                              description: The height in pixels.
                              example: 1080
                            bands:
                              type: array
                              description: A list with the bands included in the raster.
                              items:
                                type: string
                                description: The name of the band.
                              example:
                                - RED
                        statistics:
                          type: array
                          description: A list with descriptive statistics for each band of the raster file.
                          items:
                            type: object
                            description: Descriptive statistics for the n-th band.
                            properties:
                              min:
                                type: numeric
                                description: The minimun value in the band.
                                example: 0.0
                              max:
                                type: numeric
                                description: The maximum value in the band.
                                example: 255.0
                              mean:
                                type: numeric
                                description: The mean value in the band.
                                example: 180.5475
                              std:
                                type: numeric
                                description: The standard deviation in the band.
                                example: 46.4463
                        histogram:
                          type: array
                          description: The default histogram of the raster for each band.
                          items:
                            type: array
                            description: The default histogram of the n-th band. It contains the minimum and the maximum Pixel Value, the total number of pixel values, and an array with the frequencies for each Pixel Value.
                            items:
                              anyOf:
                                -
                                  type: numeric
                                  description: The minimum Pixel Value.
                                -
                                  type: numeric
                                  description: The maximum Pixel Value.
                                -
                                  type: integer
                                  description: The total number of pixel values.
                                -
                                  type: array
                                  description: An array with the frequencies for each Pixel Value (has lentgh equal to the total number of Pixel Values).
                          example: [-0.5, 255.5, 256, [2513898, 31982, 11152, 26086, 12858]]
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        resolution:
                          type: object
                          description: The resolution for each axis, and the unit of measurement.
                          properties:
                            x:
                              type: numeric
                              description: Resolution in x-axis.
                              example: 0.16726222
                            y:
                              type: numeric
                              description: Resolution in y-axis.
                              example: 0.16726222
                            unit:
                              type: string
                              description: The unit of resolution.
                              example: metre
                        cog:
                          type: boolean
                          description: In case the raster is GeoTiff, whether it is Cloud-Optimized or not.
                        numberOfBands:
                          type: integer
                          description: The number of bands in the raster.
                          example: 1
                        datatypes:
                          type: array
                          description: The data type of each band.
                          items:
                            type: string
                            description: The data type of the n-th band.
                            example: Byte
                        noDataValue:
                          type: array
                          description: The no-data value of each band.
                          items:
                            type: numeric
                            description: The no-data value of the n-th band.
                            example: null
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                          example: EPSG:4326
                        colorInterpretation:
                          type: array
                          description: The Color Interpretation for each band.
                          items:
                            type: string
                            description: The color interpretation for the n-th band.
                            example: RED
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
    mainLogger.info(f"Starting /profile/file/raster with file: {form.resource.data.filename}")
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir)
    src_file_path = uncompress_file(src_file_path)

    # Wait for results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'raster')
        response = get_resized_report(ds, form, 'raster').to_json()
        # delete_from_temp(requests_temp_dir)
        return make_response(response, 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="raster", form=form, job_type=JobType.PROFILE)
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
                    lat:
                      type: string
                      description: The column name with the latitude information
                    lon:
                      type: string
                      description: The column name with the longitude information
                    crs:
                      type: string
                      description: The dataset's crs
                    geometry:
                      type: string
                      description: The column name with the geometry information
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
                          example: vector
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        featureCount:
                          type: integer
                          description: The number of features in the dataset.
                          example: 23432
                        count:
                          type: object
                          description: Count not null values for each attribute in the dataset. The key is the attribute name.
                          additionalProperties:
                            type: integer
                            description: The not null values for the specific attribute.
                            example: 2334
                        convexHull:
                          type: string
                          description: The Well-Known-Text representation of the Convex Hull for all geometries.
                          example: POLYGON ((6.35585 49.4439, 5.73602 49.8337, 6.36222 49.4469, 6.35691 49.4439, 6.35585 49.4439))
                        convexHullStatic:
                          type: string
                          description: A PNG static map showing the convex hull, base64 encoded.
                        thumbnail:
                          type: string
                          description: A PNG thumbnail of the dataset, base64 encoded.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                          example: EPSG:4326
                        attributes:
                          type: array
                          description: A list with all attributes of the dataset.
                          items:
                            type: string
                            description: The attribute name.
                          example:
                            - attributeName1
                            - attributeName2
                            - attributeName3
                        datatypes:
                          type: object
                          description: The datatypes for each of the dataset's attributes. The key is the attribute name.
                          additionalProperties:
                            type: string
                            description: The datatype of the specific attribute.
                            examples:
                              - str
                              - int64
                              - float64
                        distribution:
                          type: object
                          description: The distribution of the values for each *categorical* attribute in the dataset. The key is the attribute name.
                          additionalProperties:
                            type: object
                            description: The frequency of each value for the specific attribute. The key is the value.
                            additionalProperties:
                              type: integer
                              description: The frequency of the specific value in the attribute.
                              example: 244
                          example:
                            categoricalAttr1:
                              value1: 632
                              value2: 432
                              value3: 332
                            categoricalAttr2:
                              value4: 434
                              value5: 232
                              value6: 134
                        quantiles:
                          type: object
                          description: The 5, 25, 50, 75, 95 quantiles for each of the numeric attributes in the dataset.
                          properties:
                            5:
                              type: object
                              description: The value of the 5-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 5-quantile value for the specific attribute.
                                example: 0.3
                            25:
                              type: object
                              description: The value of the 25-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 25-quantile value for the specific attribute.
                                example: 0.4
                            50:
                              type: object
                              description: The value of the 50-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 50-quantile value for the specific attribute.
                                example: 0.43
                            75:
                              type: object
                              description: The value of the 75-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 75-quantile value for the specific attribute.
                                example: 0.45
                            95:
                              type: object
                              description: The value of the 95-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 95-quantile value for the specific attribute.
                                example: 0.48
                        distinct:
                          type: object
                          description: The distinct values for each of the *categorical* attributes in the dataset. The key is the attribute name.
                          example:
                            categoricalAttr1:
                              - TRANSPORT
                              - SETTLEMENTS
                              - BUSINESS
                            categoricalAttr2:
                              - LU
                              - DE
                              - GR
                          additionalProperties:
                            type: array
                            description: A list with the distinct values for the specific attribute.
                            items:
                              type: string
                        recurring:
                          type: object
                          description: The most frequent values for each of the attributes in the dataset.
                        heatmap:
                          type: object
                          description: A GeoJSON with a heatmap of the geometries.
                          properties:
                            type:
                              type: string
                              example: FeatureCollection
                            features:
                              type: array
                              minItems: 0
                              description: Each feature represents a contour plot.
                              items:
                                type: object
                                properties:
                                  id:
                                    type: integer
                                  type:
                                    type: string
                                    example: Feature
                                  properties:
                                    type: object
                                    description: Style properties for the plot.
                                    properties:
                                      fill:
                                        type: string
                                        description: The hex color code for the fill.
                                        example: "#002ed1"
                                      fill-opacity:
                                        type: numeric
                                        description: The opacity for the fill color (0-1).
                                        example: 0.4
                                      stroke:
                                        type: string
                                        description: The hex color code for the stroke.
                                        example: "#002ed1"
                                      stroke-opacity:
                                        type: numeric
                                        description: The opacity for the stroke (0-1).
                                        example: 1
                                      stroke-width:
                                        type: numeric
                                        description: The width (in pixels) of the stroke.
                                        example: 1
                                      title:
                                        type: string
                                        description: The title for the specific contour.
                                        example: 0.00-1.50
                                  geometry:
                                    type: object
                                    description: The geometry of the contour.
                                    properties:
                                      type:
                                        type: string
                                        description: The geometry type.
                                        example: MultiPolygon
                                      coordinates:
                                        type: array
                                        description: The coordinates of the geometry
                                        minItems: 1
                                        items:
                                          type: array
                                          minItems: 1
                                          items:
                                            type: array
                                            minItems: 4
                                            example:
                                              -
                                                - 19.512540
                                                - 0.002680
                                              -
                                                - 19.512542
                                                - 0.002677
                                              -
                                                - 19.512545
                                                - 0.002671
                                              -
                                                - 19.512540
                                                - 0.002680
                                            items:
                                              type: array
                                              minItems: 2
                                              maxItems: 2
                                              items:
                                                type: numeric
                        heatmapStatic:
                          type: string
                          description: A PNG static heatmap, base64 encoded.
                        clusters:
                          type: object
                          description: A GeoJSON containing the clustered geometries.
                          properties:
                            type:
                              type: string
                              example: FeatureCollection
                            features:
                              type: array
                              minItems: 0
                              description: Each feature represents one cluster.
                              items:
                                type: object
                                properties:
                                  id:
                                    type: integer
                                  type:
                                    type: string
                                    example: Feature
                                  properties:
                                    type: object
                                    description: Additional properties of the cluster.
                                    properties:
                                      cluster_id:
                                        type: integer
                                        description: The cluster id.
                                      size:
                                        type: integer
                                        description: The size of the cluster; how many geometries the cluster contains.
                                        example: 420
                                  geometry:
                                    type: object
                                    description: The geometry of the cluster.
                                    properties:
                                      type:
                                        type: string
                                        description: The geometry type.
                                        example: Polygon
                                      coordinates:
                                        type: array
                                        description: The coordinates of the geometry
                                        minItems: 1
                                        items:
                                          type: array
                                          minItems: 4
                                          example:
                                            -
                                              - 5.92139730
                                              - 49.7208867
                                            -
                                              - 6.92140223
                                              - 49.7208946
                                            -
                                              - 6.92143543
                                              - 49.7202454
                                            -
                                              - 5.92139730
                                              - 49.7208867
                                          items:
                                            type: array
                                            minItems: 2
                                            maxItems: 2
                                            items:
                                              type: numeric
                        clustersStatic:
                          type: string
                          description: A PNG static map with the clustered geometries, base64 encoded.
                        statistics:
                          type: object
                          description: Descriptive statistics (*min*, *max*, *mean*, *median*, *std*, *sum*) for the numerical attributes in the dataset.
                          properties:
                            min:
                              type: object
                              description: The *minimum* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 0.4
                                attr2: 0.2
                            max:
                              type: object
                              description: The *maximum* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 10.1
                                attr2: 8.7
                            mean:
                              type: object
                              description: The *mean* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 5.2
                                attr2: 4.6
                            median:
                              type: object
                              description: The *median* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 5.3
                                attr2: 4.5
                            std:
                              type: object
                              description: The *standard deviation* for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 0.8
                                attr2: 0.6
                            sum:
                              type: object
                              description: The *sum* of of all values for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 123.3
                                attr2: 96.3
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
    mainLogger.info(f"Starting /profile/file/vector with file: {form.resource.data.filename}")
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir)
    src_file_path = uncompress_file(src_file_path)

    # Wait for results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'vector')
        report = get_resized_report(ds, form, 'vector')
        return make_response(report.to_json(), 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form, job_type=JobType.PROFILE)
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
                      description: The spatial file's.
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
                    crs:
                      type: string
                      description: The dataset's crs
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
                          description: The type of the asset (always *NetCDF*).
                          example: NetCDF
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        metadata:
                          type: object
                          description: The metadata object as written in the file. The key is a free field for the data provider, usually describing the given information.
                          additionalProperties:
                            type: string
                        dimensionsSize:
                          type: integer
                          description: The number of the dimensions.
                          example: 4
                        dimensionsList:
                          type: array
                          description: A list with the dimensions.
                          items:
                            type: string
                            description: The dimension name.
                          example:
                            - lon
                            - lat
                            - level
                            - time
                        dimensionsProperties:
                          type: object
                          description: The properties of each dimension. The key is the dimension.
                          additionalProperties:
                            type: object
                            description: "The properties of the specific dimension. **Note**: below are only the common properties; other custom properties may also be present."
                            properties:
                              type:
                                type: string
                                description: The datatype of the dimension.
                                example: float64
                              size:
                                type: integer
                                description: The size of the dimension variable.
                                example: 128
                              long_name:
                                type: string
                                description: The long name of the dimension.
                                example: longitude
                              units:
                                type: string
                                description: A description of the dimension's units.
                                example: degrees_east
                        variablesSize:
                          type: integer
                          description: Number of variables.
                          example: 12
                        variablesList:
                          type: array
                          description: A list with the variables.
                          items:
                            type: string
                            description: The name of the variable.
                          example:
                            - temperature
                            - pm1.0
                            - pm2.5
                            - pm10
                        variablesProperties:
                          type: object
                          description: The properties for each variable. The key is the variable.
                          additionalProperties:
                            type: object
                            description: "The properties of the specific variable. **Note**: below are only the common properties; other custom properties may also be present."
                            properties:
                              dimensions:
                                type: array
                                description: A list of the dimensions that this variable depends on.
                                items:
                                  type: string
                                example:
                                  - lat
                                  - lon
                              type:
                                type: string
                                description: The datatype of the variable.
                                example: float64
                              size:
                                type: integer
                                description: The size of the variable.
                                example: 128
                              units:
                                type: string
                                description: A description of the variable's units.
                                example: degrees_east
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        temporalExtent:
                          type: string
                          description: A free-text string representing the temporal extend of the dataset.
                          example: 0.000000 - 720.000000 hours
                        noDataValues:
                          type: object
                          description: The no-data value for each the variables. The key is the variable.
                          additionalProperties:
                            type: numeric
                            description: The no-data value for the specific variable.
                        statistics:
                          type: object
                          description: Descriptive statistics for each of the variables. The key is the variable.
                          additionalProperties:
                            type: object
                            description: Descriptive statistics for the specific variable.
                            properties:
                              count:
                                type: integer
                                description: The number of values for the specific variable.
                                example: 220
                              missing:
                                type: integer
                                description: The number of missing values for the specific variable.
                                example: 0
                              min:
                                type: numeric
                                description: The minimum value of the specific variable.
                                example: 0.4
                              max:
                                type: numeric
                                description: The maximum value of the specific variable.
                                example: 20.6
                              mean:
                                type: numeric
                                description: The mean value of the specific variable.
                                example: 10.7
                              std:
                                type: numeric
                                description: The standard deviation for the specific variable.
                                example: 2.4
                              variance:
                                type: numeric
                                description: The variance of the specific variable.
                                example: 7.9
                              contiguous:
                                type: boolean
                                description: Whether the data are contiguous or not.
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
    mainLogger.info(f"Starting /profile/path/netcdf with file: {form.resource.data}")
    src_file_path: str = path.join(getenv('INPUT_DIR', ''), form.resource.data)

    if not path.exists(src_file_path):
        abort(400, FILE_NOT_FOUND_MESSAGE)

    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir, input_type="path")
    src_file_path = uncompress_file(src_file_path)

    # Immediate results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'netcdf')
        report = get_resized_report(ds, form, 'netcdf')
        return make_response(report.to_json(), 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="netcdf", form=form, job_type=JobType.PROFILE)
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
                      description: The spatial file's path.
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
                          example: raster
                        info:
                          type: object
                          description: General information about the raster file.
                          properties:
                            metadata:
                              type: object
                              description: Metadata of the the raster as written in the file. The keys are free-text.
                              additionalProperties:
                                type: string
                              example:
                                AREA_OR_POINT: Point
                                TIFFTAG_MAXSAMPLEVALUE: 254
                            imageStructure:
                              type: object
                              description: Various values describing the image structure. The keys depend on the raster.
                              additionalProperties:
                                type: string
                              example:
                                COMPRESSION: YCbCr JPEG
                                INTERLEAVE: PIXEL
                                SOURCE_COLOR_SPACE: YCbCr
                            driver:
                              type: string
                              description: The driver used to open the raster.
                              example: GeoTIFF
                            files:
                              type: array
                              description: A list of the files associated with the raster.
                              items:
                                type: string
                                description: Filename.
                              example:
                                - example.tif
                            width:
                              type: integer
                              description: The width in pixels.
                              example: 1920
                            height:
                              type: integer
                              description: The height in pixels.
                              example: 1080
                            bands:
                              type: array
                              description: A list with the bands included in the raster.
                              items:
                                type: string
                                description: The name of the band.
                              example:
                                - RED
                        statistics:
                          type: array
                          description: A list with descriptive statistics for each band of the raster file.
                          items:
                            type: object
                            description: Descriptive statistics for the n-th band.
                            properties:
                              min:
                                type: numeric
                                description: The minimun value in the band.
                                example: 0.0
                              max:
                                type: numeric
                                description: The maximum value in the band.
                                example: 255.0
                              mean:
                                type: numeric
                                description: The mean value in the band.
                                example: 180.5475
                              std:
                                type: numeric
                                description: The standard deviation in the band.
                                example: 46.4463
                        histogram:
                          type: array
                          description: The default histogram of the raster for each band.
                          items:
                            type: array
                            description: The default histogram of the n-th band. It contains the minimum and the maximum Pixel Value, the total number of pixel values, and an array with the frequencies for each Pixel Value.
                            items:
                              anyOf:
                                -
                                  type: numeric
                                  description: The minimum Pixel Value.
                                -
                                  type: numeric
                                  description: The maximum Pixel Value.
                                -
                                  type: integer
                                  description: The total number of pixel values.
                                -
                                  type: array
                                  description: An array with the frequencies for each Pixel Value (has lentgh equal to the total number of Pixel Values).
                          example: [-0.5, 255.5, 256, [2513898, 31982, 11152, 26086, 12858]]
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        resolution:
                          type: object
                          description: The resolution for each axis, and the unit of measurement.
                          properties:
                            x:
                              type: numeric
                              description: Resolution in x-axis.
                              example: 0.16726222
                            y:
                              type: numeric
                              description: Resolution in y-axis.
                              example: 0.16726222
                            unit:
                              type: string
                              description: The unit of resolution.
                              example: metre
                        cog:
                          type: boolean
                          description: In case the raster is GeoTiff, whether it is Cloud-Optimized or not.
                        numberOfBands:
                          type: integer
                          description: The number of bands in the raster.
                          example: 1
                        datatypes:
                          type: array
                          description: The data type of each band.
                          items:
                            type: string
                            description: The data type of the n-th band.
                            example: Byte
                        noDataValue:
                          type: array
                          description: The no-data value of each band.
                          items:
                            type: numeric
                            description: The no-data value of the n-th band.
                            example: null
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                          example: EPSG:4326
                        colorInterpretation:
                          type: array
                          description: The Color Interpretation for each band.
                          items:
                            type: string
                            description: The color interpretation for the n-th band.
                            example: RED
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
    mainLogger.info(f"Starting /profile/path/raster with file: {form.resource.data}")
    src_file_path: str = path.join(getenv('INPUT_DIR', ''), form.resource.data)

    if not path.exists(src_file_path):
        abort(400, FILE_NOT_FOUND_MESSAGE)

    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir, input_type="path")
    src_file_path = uncompress_file(src_file_path)

    # Wait for results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'raster')
        response = get_resized_report(ds, form, 'raster').to_json()
        return make_response(response, 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="raster", form=form, job_type=JobType.PROFILE)
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
                      description: The spatial file's path.
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
                    crs:
                      type: string
                      description: The dataset's crs
                    geometry:
                      type: string
                      description: The column name with the geometry information
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
                          example: vector
                        mbr:
                          type: string
                          description: The Well-Known-Text representation of the Minimum Bounding Rectangle (MBR).
                          example: POLYGON ((6.5206 49.4439, 6.5206 50.1845, 5.73398 50.1845, 5.73398 49.4439, 6.5206 49.4439))
                        mbrStatic:
                          type: string
                          description: A PNG static map with the MBR, base64 encoded.
                        featureCount:
                          type: integer
                          description: The number of features in the dataset.
                          example: 23432
                        count:
                          type: object
                          description: Count not null values for each attribute in the dataset. The key is the attribute name.
                          additionalProperties:
                            type: integer
                            description: The not null values for the specific attribute.
                            example: 2334
                        convexHull:
                          type: string
                          description: The Well-Known-Text representation of the Convex Hull for all geometries.
                          example: POLYGON ((6.35585 49.4439, 5.73602 49.8337, 6.36222 49.4469, 6.35691 49.4439, 6.35585 49.4439))
                        convexHullStatic:
                          type: string
                          description: A PNG static map showing the convex hull, base64 encoded.
                        thumbnail:
                          type: string
                          description: A PNG thumbnail of the dataset, base64 encoded.
                        crs:
                          type: string
                          description: The short name of the dataset's native Coordinate Reference System (CRS).
                          example: EPSG:4326
                        attributes:
                          type: array
                          description: A list with all attributes of the dataset.
                          items:
                            type: string
                            description: The attribute name.
                          example:
                            - attributeName1
                            - attributeName2
                            - attributeName3
                        datatypes:
                          type: object
                          description: The datatypes for each of the dataset's attributes. The key is the attribute name.
                          additionalProperties:
                            type: string
                            description: The datatype of the specific attribute.
                            examples:
                              - str
                              - int64
                              - float64
                        distribution:
                          type: object
                          description: The distribution of the values for each *categorical* attribute in the dataset. The key is the attribute name.
                          additionalProperties:
                            type: object
                            description: The frequency of each value for the specific attribute. The key is the value.
                            additionalProperties:
                              type: integer
                              description: The frequency of the specific value in the attribute.
                              example: 244
                          example:
                            categoricalAttr1:
                              value1: 632
                              value2: 432
                              value3: 332
                            categoricalAttr2:
                              value4: 434
                              value5: 232
                              value6: 134
                        quantiles:
                          type: object
                          description: The 5, 25, 50, 75, 95 quantiles for each of the numeric attributes in the dataset.
                          properties:
                            5:
                              type: object
                              description: The value of the 5-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 5-quantile value for the specific attribute.
                                example: 0.3
                            25:
                              type: object
                              description: The value of the 25-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 25-quantile value for the specific attribute.
                                example: 0.4
                            50:
                              type: object
                              description: The value of the 50-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 50-quantile value for the specific attribute.
                                example: 0.43
                            75:
                              type: object
                              description: The value of the 75-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 75-quantile value for the specific attribute.
                                example: 0.45
                            95:
                              type: object
                              description: The value of the 95-quantile for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                                description: The 95-quantile value for the specific attribute.
                                example: 0.48
                        distinct:
                          type: object
                          description: The distinct values for each of the *categorical* attributes in the dataset. The key is the attribute name.
                          example:
                            categoricalAttr1:
                              - TRANSPORT
                              - SETTLEMENTS
                              - BUSINESS
                            categoricalAttr2:
                              - LU
                              - DE
                              - GR
                          additionalProperties:
                            type: array
                            description: A list with the distinct values for the specific attribute.
                            items:
                              type: string
                        recurring:
                          type: object
                          description: The most frequent values for each of the attributes in the dataset.
                        heatmap:
                          type: object
                          description: A GeoJSON with a heatmap of the geometries.
                          properties:
                            type:
                              type: string
                              example: FeatureCollection
                            features:
                              type: array
                              minItems: 0
                              description: Each feature represents a contour plot.
                              items:
                                type: object
                                properties:
                                  id:
                                    type: integer
                                  type:
                                    type: string
                                    example: Feature
                                  properties:
                                    type: object
                                    description: Style properties for the plot.
                                    properties:
                                      fill:
                                        type: string
                                        description: The hex color code for the fill.
                                        example: "#002ed1"
                                      fill-opacity:
                                        type: numeric
                                        description: The opacity for the fill color (0-1).
                                        example: 0.4
                                      stroke:
                                        type: string
                                        description: The hex color code for the stroke.
                                        example: "#002ed1"
                                      stroke-opacity:
                                        type: numeric
                                        description: The opacity for the stroke (0-1).
                                        example: 1
                                      stroke-width:
                                        type: numeric
                                        description: The width (in pixels) of the stroke.
                                        example: 1
                                      title:
                                        type: string
                                        description: The title for the specific contour.
                                        example: 0.00-1.50
                                  geometry:
                                    type: object
                                    description: The geometry of the contour.
                                    properties:
                                      type:
                                        type: string
                                        description: The geometry type.
                                        example: MultiPolygon
                                      coordinates:
                                        type: array
                                        description: The coordinates of the geometry
                                        minItems: 1
                                        items:
                                          type: array
                                          minItems: 1
                                          items:
                                            type: array
                                            minItems: 4
                                            example:
                                              -
                                                - 19.512540
                                                - 0.002680
                                              -
                                                - 19.512542
                                                - 0.002677
                                              -
                                                - 19.512545
                                                - 0.002671
                                              -
                                                - 19.512540
                                                - 0.002680
                                            items:
                                              type: array
                                              minItems: 2
                                              maxItems: 2
                                              items:
                                                type: numeric
                        heatmapStatic:
                          type: string
                          description: A PNG static heatmap, base64 encoded.
                        clusters:
                          type: object
                          description: A GeoJSON containing the clustered geometries.
                          properties:
                            type:
                              type: string
                              example: FeatureCollection
                            features:
                              type: array
                              minItems: 0
                              description: Each feature represents one cluster.
                              items:
                                type: object
                                properties:
                                  id:
                                    type: integer
                                  type:
                                    type: string
                                    example: Feature
                                  properties:
                                    type: object
                                    description: Additional properties of the cluster.
                                    properties:
                                      cluster_id:
                                        type: integer
                                        description: The cluster id.
                                      size:
                                        type: integer
                                        description: The size of the cluster; how many geometries the cluster contains.
                                        example: 420
                                  geometry:
                                    type: object
                                    description: The geometry of the cluster.
                                    properties:
                                      type:
                                        type: string
                                        description: The geometry type.
                                        example: Polygon
                                      coordinates:
                                        type: array
                                        description: The coordinates of the geometry
                                        minItems: 1
                                        items:
                                          type: array
                                          minItems: 4
                                          example:
                                            -
                                              - 5.92139730
                                              - 49.7208867
                                            -
                                              - 6.92140223
                                              - 49.7208946
                                            -
                                              - 6.92143543
                                              - 49.7202454
                                            -
                                              - 5.92139730
                                              - 49.7208867
                                          items:
                                            type: array
                                            minItems: 2
                                            maxItems: 2
                                            items:
                                              type: numeric
                        clustersStatic:
                          type: string
                          description: A PNG static map with the clustered geometries, base64 encoded.
                        statistics:
                          type: object
                          description: Descriptive statistics (*min*, *max*, *mean*, *median*, *std*, *sum*) for the numerical attributes in the dataset.
                          properties:
                            min:
                              type: object
                              description: The *minimum* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 0.4
                                attr2: 0.2
                            max:
                              type: object
                              description: The *maximum* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 10.1
                                attr2: 8.7
                            mean:
                              type: object
                              description: The *mean* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 5.2
                                attr2: 4.6
                            median:
                              type: object
                              description: The *median* value for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 5.3
                                attr2: 4.5
                            std:
                              type: object
                              description: The *standard deviation* for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 0.8
                                attr2: 0.6
                            sum:
                              type: object
                              description: The *sum* of of all values for each of the numeric attributes. The key is the attribute name.
                              additionalProperties:
                                type: numeric
                              example:
                                attr1: 123.3
                                attr2: 96.3
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
    mainLogger.info(f"Starting /profile/path/vector with file: {form.resource.data}")
    src_file_path: str = path.join(getenv('INPUT_DIR', ''), form.resource.data)

    if not path.exists(src_file_path):
        abort(400, FILE_NOT_FOUND_MESSAGE)

    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(PROFILE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir, input_type="path")
    src_file_path = uncompress_file(src_file_path)

    # Wait for results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        ds = get_ds(src_file_path, form, 'vector')
        report = get_resized_report(ds, form, 'vector')
        return make_response(report.to_json(), 200)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form, job_type=JobType.PROFILE)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


def normalize_endpoint(form: FlaskForm, src_file_path: str, ticket: str, requests_temp_dir: str):
    # Immediate results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        gdf = get_ds(src_file_path, form, 'vector')
        gdf = normalize_gdf(form, gdf)
        file_name = path.split(src_file_path)[1].split('.')[0] + '_normalized'
        output_file = store_gdf(gdf, form.resource_type.data, file_name, requests_temp_dir)
        file_content = open(output_file, 'rb')
        return send_file(file_content, attachment_filename=path.basename(output_file), as_attachment=True)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form, job_type=JobType.NORMALIZE)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/normalize/file", methods=["POST"])
def normalize_file():
    """Normalize a vector or tabular file that its provided with the request
        ---
        post:
          summary: Normalize a vector file that is provided with the request
          tags:
            - Normalize
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
                    resource_type:
                      type: string
                      enum: [csv, shp]
                      description: The file type of the resource
                    csv_delimiter:
                      type: string
                      default: The program will try to detect it automatically
                      description: The csv file's delimiter if applicable
                    crs:
                      type: string
                      description: The dataset's crs
                    date_normalization:
                      type: list
                      description: The names of the columns to perform date normalization
                    phone_normalization:
                      type: list
                      description: The names of the columns to perform phone normalization
                    special_character_normalization:
                      type: list
                      description: The names of the columns to perform special character normalization
                    alphabetical_normalization:
                      type: list
                      description: The names of the columns to perform alphabetical normalization
                    case_normalization:
                      type: list
                      description: The names of the columns to perform case normalization
                    transliteration:
                      type: list
                      description:  The names of the columns to perform transliteration
                    transliteration_langs:
                      type: list
                      description: The languages contained in the column we want to transliterate
                    transliteration_lang:
                      type: string
                      description: The language contained in the column we want to transliterate
                    value_cleaning:
                      type: list
                      description: The names of the columns to perform value cleaning
                    wkt_normalization:
                      type: boolean
                      description: Whether to perform wkt normalization or not
                    column_name_normalization:
                      type: boolean
                      description: Whether to perform column name normalization or not
                  required:
                    - resource
                    - resource_type
          responses:
            200:
              description: The input file with all the specified normalizations applied.
              content:
                oneOf:
                  - application/csv:
                      schema:
                        type: object
                  - application/zip:
                      schema:
                        type: object
            202:
              description: Accepted for processing, but normalization has not been completed.
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
    form = NormalizeFileForm()
    validate_form(form, mainLogger)
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(NORMALIZE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir)
    src_file_path = uncompress_file(src_file_path)
    return normalize_endpoint(form, src_file_path, ticket, requests_temp_dir)


@app.route("/normalize/path", methods=["POST"])
def normalize_path():
    """Normalize a vector or tabular file that its path is provided with the request
        ---
        post:
          summary: Normalize a vector file that its path is provided with the request
          tags:
            - Normalize
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
                      description: The spatial file's path.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    resource_type:
                      type: string
                      enum: [csv, shp]
                      description: The file type of the resource
                    csv_delimiter:
                      type: string
                      default: The program will try to detect it automatically
                      description: The csv file's delimiter if applicable
                    crs:
                      type: string
                      description: The dataset's crs
                    date_normalization:
                      type: list
                      description: The names of the columns to perform date normalization
                    phone_normalization:
                      type: list
                      description: The names of the columns to perform phone normalization
                    special_character_normalization:
                      type: list
                      description: The names of the columns to perform special character normalization
                    alphabetical_normalization:
                      type: list
                      description: The names of the columns to perform alphabetical normalization
                    case_normalization:
                      type: list
                      description: The names of the columns to perform case normalization
                    transliteration:
                      type: list
                      description:  The names of the columns to perform transliteration
                    transliteration_langs:
                      type: list
                      description: The languages contained in the column we want to transliterate
                    transliteration_lang:
                      type: string
                      description: The language contained in the column we want to transliterate
                    value_cleaning:
                      type: list
                      description: The names of the columns to perform value cleaning
                    wkt_normalization:
                      type: boolean
                      description: Whether to perform wkt normalization or not
                    column_name_normalization:
                      type: boolean
                      description: Whether to perform column name normalization or not
                  required:
                    - resource
                    - resource_type
          responses:
            200:
              description: The input file with all the specified normalizations applied.
              content:
                oneOf:
                  - application/csv:
                      schema:
                        type: object
                  - application/zip:
                      schema:
                        type: object
            202:
              description: Accepted for processing, but normalization has not been completed.
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
    form = NormalizePathForm()
    validate_form(form, mainLogger)
    src_file_path: str = path.join(getenv('INPUT_DIR', ''), form.resource.data)
    if not path.exists(src_file_path):
        abort(400, FILE_NOT_FOUND_MESSAGE)
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(NORMALIZE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir, input_type="path")
    src_file_path = uncompress_file(src_file_path)
    return normalize_endpoint(form, src_file_path, ticket, requests_temp_dir)


def summarize_endpoint(form: FlaskForm, src_file_path: str, ticket: str, requests_temp_dir: str):
    # Immediate results
    if form.response.data == "prompt":
        @after_this_request
        def cleanup_temp(resp):
            delete_from_temp(requests_temp_dir)
            return resp
        gdf = get_ds(src_file_path, form, 'vector')
        json_summary = summarize(gdf, form)
        return jsonify(json_summary)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector", form=form, job_type=JobType.SUMMARIZE)
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/summarize/file", methods=["POST"])
def summarize_file():
    """Summarize a vector or tabular file that its provided with the request
        ---
        post:
          summary: Summarize a vector or tabular file that its provided with the request
          tags:
            - Summarize
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
                    resource_type:
                      type: string
                      enum: [csv, shp]
                      description: The file type of the resource
                    csv_delimiter:
                      type: string
                      default: The program will try to detect it automatically
                      description: The csv file's delimiter if applicable
                    crs:
                      type: string
                      description: The dataset's crs

                    sampling_method:
                      type: string
                      enum: [random, stratified, cluster]
                      description: The sampling method to apply for the tabular data
                    columns_to_sample:
                      type: list
                      description: The names of the columns to sample
                    n_samples:
                      type: integer
                      description: The amount of samples
                    n_clusters:
                      type: integer
                      description: The number of clusters (applies only to the clustering method)
                    n_sample_per_cluster:
                      type: integer
                      description: The amount of samples per cluster (applies only to the clustering method)
                    clustering_column_name:
                      type: list
                      description:  The column name to base the clustering (applies only to the clustering method)
                    to_stratify:
                      type: list
                      description: The columns that need to produce stratified samples
                    columns_to_hist:
                      type: list
                      description: The columns to take their histograms
                    n_buckets:
                      type: list
                      description: The number of buckets per histogram
                    geometry_sampling_bounding_box:
                      type: list
                      description: The bounding box to get samples within it in the format [xmin, ymin, xmax, ymax]
                    geometry_simplification_tolerance:
                      type: float
                      description: The tolerance for the geometric simplification
                  required:
                    - resource
                    - resource_type
          responses:
            200:
              description: The generated summaries.
              content:
                oneOf:
                  - application/json:
                      schema:
                        type: object
            202:
              description: Accepted for processing, but summarization has not been completed.
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
    form = SummarizeFileForm()
    validate_form(form, mainLogger)
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(SUMMARIZE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir)
    return summarize_endpoint(form, src_file_path, ticket, requests_temp_dir)


@app.route("/summarize/path", methods=["POST"])
def summarize_path():
    """Summarize a vector or tabular file that its path is provided with the request
        ---
        post:
          summary: Summarize a vector file that its path is provided with the request
          tags:
            - Summarize
          requestBody:
            required: true
            content:
               multipart/form-data:
                schema:
                  type: object
                  properties:
                    resource:
                      type: string
                      description: The spatial file's path.
                    response:
                      type: string
                      enum: [prompt, deferred]
                      default: prompt
                      description: Determines whether the profile process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                    resource_type:
                      type: string
                      enum: [csv, shp]
                      description: The file type of the resource
                    csv_delimiter:
                      type: string
                      default: The program will try to detect it automatically
                      description: The csv file's delimiter if applicable
                    crs:
                      type: string
                      description: The dataset's crs

                    sampling_method:
                      type: string
                      enum: [random, stratified, cluster]
                      description: The sampling method to apply for the tabular data
                    columns_to_sample:
                      type: list
                      description: The names of the columns to sample
                    n_samples:
                      type: integer
                      description: The amount of samples
                    n_clusters:
                      type: integer
                      description: The number of clusters (applies only to the clustering method)
                    n_sample_per_cluster:
                      type: integer
                      description: The amount of samples per cluster (applies only to the clustering method)
                    clustering_column_name:
                      type: list
                      description:  The column name to base the clustering (applies only to the clustering method)
                    to_stratify:
                      type: list
                      description: The columns that need to produce stratified samples
                    columns_to_hist:
                      type: list
                      description: The columns to take their histograms
                    n_buckets:
                      type: list
                      description: The number of buckets per histogram
                    geometry_sampling_bounding_box:
                      type: list
                      description: The bounding box to get samples within it in the format [xmin, ymin, xmax, ymax]
                    geometry_simplification_tolerance:
                      type: float
                      description: The tolerance for the geometric simplification
                  required:
                    - resource
                    - resource_type
          responses:
            200:
              description: The generated summaries.
              content:
                oneOf:
                  - application/json:
                      schema:
                        type: object
            202:
              description: Accepted for processing, but summarization has not been completed.
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
    form = SummarizePathForm()
    validate_form(form, mainLogger)
    src_file_path: str = path.join(getenv('INPUT_DIR', ''), form.resource.data)
    if not path.exists(src_file_path):
        abort(400, FILE_NOT_FOUND_MESSAGE)
    ticket: str = create_ticket()
    requests_temp_dir: str = path.join(SUMMARIZE_TEMP_DIR, ticket)
    src_file_path: str = save_to_temp(form, requests_temp_dir, input_type="path")
    src_file_path = uncompress_file(src_file_path)
    return summarize_endpoint(form, src_file_path, ticket, requests_temp_dir)


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
    spec.path(view=normalize_file)
    spec.path(view=normalize_path)
    spec.path(view=summarize_file)
    spec.path(view=summarize_path)
    spec.path(view=status)
    spec.path(view=resource)
