# Profile micro-service

[![Build Status](https://ci.dev-1.opertusmundi.eu:9443/api/badges/OpertusMundi/profile/status.svg?ref=refs/heads/main)](https://ci.dev-1.opertusmundi.eu:9443/OpertusMundi/profile)

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
- `INPUT_DIR`: The input directory; all input paths will be resolved under this directory. 
- `OUTPUT_DIR`: The location (full path), which will be used to store the resulting files (for the case of *deferred* request, see below).
- (optional) `TEMPDIR`: The location of storing temporary files. If not set, the system temporary path location will be used.
- (optional) `CORS`: List or string of allowed origins. Default: \*.
- (optional) `LOGGING_FILE_CONFIG`: Logging configuration file, otherwise the default logging configuration file will be used.
- (optional) `LOGGING_ROOT_LEVEL`: The level of detail for the root logger; one of `DEBUG`, `INFO`, `WARNING`.
- (optional) `SQLALCHEMY_POOL_SIZE`: The size of the pool to be maintained \[default: 5\].
- (optional) `SQLALCHEMY_POOL_RECYCLE`:  This parameter prevents the pool from using a particular connection that has passed a certain age (in seconds) \[default: 1800\].
- (optional) `SQLALCHEMY_POOL_TIMEOUT`: Number of seconds to wait before giving up on getting a connection from the pool \[default: 10\].
- (optional) `SQLALCHEMY_PRE_PING`: Boolean value, if True will enable the connection pool “pre-ping” feature that tests connections for liveness upon each checkout \[default: True\].

A development server could be started with:
```
flask run
```

## Endpoints

You can browse the full [OpenAPI documentation](https://opertusmundi.github.io/profile/)

### Documentation
* `/` Generates the OpenAPI documentation
### Profiling with file input
* `/profile/file/netcdf` Profile a NetCDF file that is provided with the request
* `/profile/file/raster` Profile a raster file that is provided with the request
* `/profile/file/vector` Profile a vector file that is provided with the request

Parameters (form-data):
* `resource (Required)` The given file
* `response (Optional, default="prompt")` (see below)
* `basemap_provider (Optional, default="OpenStreetMap")` The basemap provider
* `basemap_name (Optional, default="Mapnik")` The name of the basemap
* `aspect_ratio (Optional)` The aspect ratio of the static map to be generated
* `width (Optional)` The width (in pixels) of the static map to be generated
* `height (Optional)` The height (in pixels) of the static map to be generated
* `lat (Optional)` The column name containing the latitude information
* `lon (Optional)` The column name containing the longitude information
* `time (Optional)` The column name containing the time information
* `crs (Optional)` The crs
* `geometry (Optional, default="wkt")` The column name containing the geometry information


### Profiling with path input
* `/profile/path/netcdf` Profile a NetCDF file that its path is provided with the request
* `/profile/path/raster` Profile a raster file that its path is provided with the request
* `/profile/path/vector` Profile a vector file that its path is provided with the request

Parameters (x-www-form-urlencoded):
* `resource (Required)` The file's path
* `response (Optional, default="prompt")` (see below)
* `basemap_provider (Optional, default="OpenStreetMap")` The basemap provider
* `basemap_name (Optional, default="Mapnik")` The name of the basemap
* `aspect_ratio (Optional)` The aspect ratio of the static map to be generated
* `width (Optional)` The width (in pixels) of the static map to be generated
* `height (Optional)` The height (in pixels) of the static map to be generated
* `lat (Optional)` The column name containing the latitude information
* `lon (Optional)` The column name containing the longitude information
* `time (Optional)` The column name containing the time information
* `crs (Optional)` The crs
* `geometry (Optional, default="wkt")` The column name containing the geometry information


### Normalization with file input
* `/normalize/file` Normalize a vector or tabular file that is provided with the request 

Parameters (form-data):
* `resource (Required)` The given file
* `resource_type (Required)` The resource type either csv or shp
* `response (Optional, default="prompt")` (see below)
* `csv_delimiter (Optional, default=automated)` The delimiter of the provided csv file
* `crs (Optional)` The crs
* `date_normalization (Optional)` The names of the columns to perform date normalization
* `phone_normalization (Optional)` The names of the columns to perform phone normalization
* `special_character_normalization (Optional)`  The names of the columns to perform special character normalization
* `alphabetical_normalization (Optional)` The names of the columns to perform alphabetical normalization
* `case_normalization (Optional)` The names of the columns to perform case normalization
* `transliteration (Optional)` The names of the columns to perform transliteration
* `transliteration_langs (Optional)` The languages contained in the column we want to transliterate
* `transliteration_lang (Optional)`  The language contained in the column we want to transliterate
* `value_cleaning (Optional)`The names of the columns to perform value cleaning
* `wkt_normalization (Optional)` Whether to perform wkt normalization or not
* `column_name_normalization (Optional)` Whether to perform column name normalization or not


### Normalization with path input
* `/normalize/path` Normalize a vector or tabular file that its path is provided with the request

Parameters (x-www-form-urlencoded):
* `resource (Required)` The file's path
* `resource_type (Required)` The resource type either csv or shp
* `response (Optional, default="prompt")` (see below)
* `csv_delimiter (Optional, default=automated)` The delimiter of the provided csv file
* `crs (Optional)` The crs
* `date_normalization (Optional)` The names of the columns to perform date normalization
* `phone_normalization (Optional)` The names of the columns to perform phone normalization
* `special_character_normalization (Optional)`  The names of the columns to perform special character normalization
* `alphabetical_normalization (Optional)` The names of the columns to perform alphabetical normalization
* `case_normalization (Optional)` The names of the columns to perform case normalization
* `transliteration (Optional)` The names of the columns to perform transliteration
* `transliteration_langs (Optional)` The languages contained in the column we want to transliterate
* `transliteration_lang (Optional)`  The language contained in the column we want to transliterate
* `value_cleaning (Optional)`The names of the columns to perform value cleaning
* `wkt_normalization (Optional)` Whether to perform wkt normalization or not
* `column_name_normalization (Optional)` Whether to perform column name normalization or not


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

You need to configure the network to attach to. For example, you can create a private network named `opertusmundi_network`:

    docker network create --attachable opertusmundi_network

You also need to configure for volumes used for input/output data. For example, you can create a named volume `opertusmundi_profile_input`:

    docker volume create opertusmundi_profile_input

Build:

    docker-compose -f compose.yml build

Prepare the following files/directories:

   * `./data/geoprofile.sqlite`:  the SQLite database (an empty database, if running for first time)
   * `./secrets/secret_key`: file needed for signing/encrypting session data
   * `./logs`: a directory to keep logs under
   * `./temp`: a directory to use as scratch space

Start application:
    
    docker-compose -f compose.yml up


## Run tests

Copy `compose-testing.yml.example` to `compose-testing.yml` and adjust to your needs. This is a just a docker-compose recipe for setting up the testing container.

Run nosetests (in an ephemeral container):

    docker-compose -f compose-testing.yml run --rm --user "$(id -u):$(id -g)" nosetests -v

