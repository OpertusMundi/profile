# Profile micro-service

[![Build Status](https://ci.dev-1.opertusmundi.eu:9443/api/badges/OpertusMundi/profile/status.svg?ref=refs/heads/master)](https://ci.dev-1.opertusmundi.eu:9443/OpertusMundi/profile)

## Description

The purpose of this package is to deploy a micro-service which profiles a spatial (vector or raster) file. 

## Installation

The package requires at least Python 3.7, *GDAL 3.1.*, *sqlite3*, *[geovaex](https://github.com/OpertusMundi/geovaex)* 
and [BigDataVoyant](https://github.com/OpertusMundi/BigDataVoyant). 
To install with **pip**:
```
pip install git+https://github.com/OpertusMundi/profile.git
```
Initialize sqlite database by running:
```
flask init-db
```

The following environment variables should be set:
- `FLASK_ENV`: `development` or `production`
- `FLASK_APP`: `geoprofile` (will be automatically set if running as a container)
- `OUTPUT_DIR`: The location (full path), which will be used to store the resulting files (for the case of *deferred* request, see below).
- (optional) `TEMPDIR`: The location of storing temporary files. If not set, the system temporary path location will be used.
- (optional) `CORS`: List or string of allowed origins. Default: \*.
- (optional) `LOGGING_FILE_CONFIG`: Logging configuration file, otherwise the default logging configuration file will be used.

A development server could be started with:
```
flask run
```

## Endpoints

### Documentation
* `/` Generates the OpenAPI documentation
### Profiling with file input
* `/profile/file/netcdf` Profile a NetCDF file that is provided with the request
* `/profile/file/raster` Profile a raster file that is provided with the request
* `/profile/file/vector` Profile a vector file that is provided with the request

Required parameters (form-data):
* `resource (Required)` The given file
* `response (Optional, default=prompt)` (see below)

### Profiling with path input
* `/profile/path/netcdf` Profile a NetCDF file that its path is provided with the request
* `/profile/path/raster` Profile a raster file that its path is provided with the request
* `/profile/path/vector` Profile a vector file that its path is provided with the request

Required parameters (x-www-form-urlencoded):
* `resource (Required)` The file's path
* `response (Optional, default=prompt)` (see below)

### Deferred processing support
* `/status/<ticket>` Get the status of a specific ticket
* `/resource/<ticket>` Get the resulted resource associated with a specific ticket

Required parameters:
* `<ticket>` The ticket as part of the request path

In each case, the requester could determine whether the service should promptly initiate the profiling process 
and wait to finish in order to return the response (**prompt** response) or should response immediately returning 
a ticket with the request (**deferred** response). In latter case, one could request */status/\<ticket\>* and 
*/resource/\<ticket\>* in order to get the status and the resulting file corresponding to a specific ticket.

Once deployed, info about the endpoints and their possible HTTP parameters could be obtained by requesting the 
index of the service, i.e. for development environment http://localhost:5000.

## Build and run as a container

Copy `.env.example` to `.env` and configure if needed (e.g `FLASK_ENV` variable).

Copy `compose.yml.example` to `compose.yml` (or `docker-compose.yml`) and adjust to your needs (e.g. specify volume source locations etc.).

Build:

    docker-compose -f compose.yml build

Prepare the following files/directories:

   * `./data/geoprofile.sqlite`:  the SQLite database (an empty database, if running for first time)
   * `./data/secret_key`: file needed for signing/encrypting session data
   * `./logs`: a directory to keep logs under
   * `./output`: a directory to be used as root of a hierarchy of output files

Start application:
    
    docker-compose -f compose.yml up


## Run tests

Copy `compose-testing.yml.example` to `compose-testing.yml` and adjust to your needs. This is a just a docker-compose recipe for setting up the testing container.

Run nosetests (in an ephemeral container):

    docker-compose -f compose-testing.yml run --rm --user "$(id -u):$(id -g)" nosetests -v

