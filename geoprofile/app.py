from datetime import datetime, timezone
import json
from flask import Flask
from apispec import APISpec
from apispec_webframeworks.flask import FlaskPlugin
from os import path, getenv, stat
from flask_cors import CORS
from flask_executor import Executor
from flask import jsonify
from flask import make_response, send_file

import bigdatavoyant as bdv
from bigdatavoyant import RasterData

from . import db
from .forms import ProfileFileForm, ProfilePathForm
from .logging import getLoggers
from .utils import create_ticket, get_tmp_dir, mkdir, validate_form, save_to_temp, uncompress_file


if getenv('OUTPUT_DIR') is None:
    raise Exception('Environment variable OUTPUT_DIR is not set.')

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
def enqueue(ticket: str, src_path: str, file_type: str) -> tuple:
    """Enqueue a profile job (in case requested response type is 'deferred')."""
    filesize = stat(src_path).st_size
    dbc = db.get_db()
    dbc.execute('INSERT INTO tickets (ticket, filesize) VALUES(?, ?);', [ticket, filesize])
    dbc.commit()
    dbc.close()
    try:
        result = {}
        if file_type == 'netcdf':
            ds = bdv.io.read_file(src_path, type='netcdf', lat_attr='lat')
            result = ds.report(sample_bbox=[-20, -20, 20, 20], sample_filename='sample.nc')
        elif file_type == 'raster':
            ds = RasterData.from_file(src_path)
            result = ds.report()
        elif file_type == 'vector':
            src_path = uncompress_file(src_path)
            gdf = bdv.io.read_file(src_path)
            result = gdf.profiler.report()
    except Exception as e:
        return ticket, None, 0, str(e)
    else:
        return ticket, result, 1, None


@app.route("/")
def index():
    """The index route, gives info about the API endpoints."""
    mainLogger.info('Generating OpenAPI document...')
    return make_response(spec.to_dict(), 200)


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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        ds = bdv.io.read_file(src_file_path, type='netcdf', lat_attr='lat')
        report = ds.report(sample_bbox=[-20, -20, 20, 20], sample_filename='sample.nc')
        return jsonify(report)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="netcdf")
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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        ds = RasterData.from_file(src_file_path)
        report = ds.report()
        return jsonify(report)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="raster")
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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        gdf = bdv.io.read_file(src_file_path)
        report = gdf.profiler.report()
        return jsonify(report)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="vector")
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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        ds = bdv.io.read_file(src_file_path, type='netcdf', lat_attr='lat')
        report = ds.report(sample_bbox=[-20, -20, 20, 20], sample_filename='sample.nc')
        return jsonify(report)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="netcdf")
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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        ds = RasterData.from_file(src_file_path)
        report = ds.report()
        return jsonify(report)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="raster")
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
                      description: Determines whether the transform process should be promptly initiated (*prompt*) or queued (*deferred*). In the first case, the response waits for the result, in the second the response is immediate returning a ticket corresponding to the request.
                  required:
                    - resource
          responses:
            200:
              description: Profiling completed and returned.
              content:
                application/json:
                  schema:
                    type: object
            202:
              description: Accepted for processing, but transform has not been completed.
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
        gdf = bdv.io.read_file(src_file_path)
        report = gdf.profiler.report()
        return jsonify(report)
    # Wait for results
    else:
        ticket: str = create_ticket()
        enqueue.submit(ticket, src_file_path, file_type="vector")
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/status/<ticket>")
def status(ticket):
    """Get the status of a specific ticket.
    ---
    get:
      summary: Get the status of a transform request.
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
                    description: Whether transformation process has been completed or not.
                  success:
                    type: boolean
                    description: Whether transformation process completed succesfully.
                  comment:
                    type: string
                    description: If transformation has failed, a short comment describing the reason.
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
      summary: Get the resource associated to a transform request.
      description: Returns the resource resulted from a transform request corresponding to a specific ticket.
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
          description: The transformed compressed spatial file.
          content:
            application/x-tar:
              schema:
                type: string
                format: binary
        404:
          description: Ticket not found or transform has not been completed.
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
