#!/bin/bash
set -u -e -o pipefail

[[ "${DEBUG:-f}" != "f" || "${XTRACE:-f}" != "f" ]] && set -x

# Check environment

python_version="$(python3 -c 'import platform; print(platform.python_version())' | cut -d '.' -f 1,2)"
if [ "${python_version}" != "${PYTHON_VERSION}" ]; then
    echo "PYTHON_VERSION (${PYTHON_VERSION}) different with version reported from python3 executable (${python_version})" 1>&2
    exit 1
fi

if [ ! -f "${SECRET_KEY_FILE}" ]; then
    echo "SECRET_KEY_FILE does not exist!" 1>&2 && exit 1
fi

if [ ! -d "${OUTPUT_DIR}" ]; then
    echo "OUTPUT_DIR is not a directory!" 1>&2 && exit 1 
fi
if [ ! -w "${OUTPUT_DIR}" ]; then
    echo "OUTPUT_DIR is not writable!" 1>&2 && exit 1 
fi

if [ ! -d "${INPUT_DIR}" ]; then
    echo "INPUT_DIR is not a directory!" 1>&2 && exit 1 
fi
if [ ! -r "${INPUT_DIR}" ]; then
    echo "INPUT_DIR is not readable!" 1>&2 && exit 1 
fi

if [ ! -f "${DB_PASS_FILE}" ]; then
    echo "DB_PASS_FILE does not exist!" 1>&2 && exit 1
fi

if [ ! -f "${LOGGING_FILE_CONFIG}" ]; then
    echo "LOGGING_FILE_CONFIG (configuration for Python logging) does not exist!" 1>&2 && exit 1
fi

logging_file_config=${LOGGING_FILE_CONFIG}

if [ -n "${LOGGING_ROOT_LEVEL}" ]; then
    logging_file_config=$(mktemp logging-XXXXXXXX.conf)
    sed -e "/^\[logger_root\]/,/^\[.*/ { s/^level=.*/level=${LOGGING_ROOT_LEVEL}/ }" ${LOGGING_FILE_CONFIG} \
        > ${logging_file_config}
fi

DB_PASS="$(cat ${DB_PASS_FILE} | tr -d '\n')"
export DATABASE_URI="${DB_ENGINE}://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
export FLASK_APP="geoprofile"
export SECRET_KEY="$(cat "${SECRET_KEY_FILE}")"

# Initialize database

flask init-db

# Configure and start WSGI server

if [ "${FLASK_ENV}" = "development" ]; then
    # Run a development server
    exec /usr/local/bin/wsgi.py
fi

num_workers="${NUM_WORKERS:-4}"
server_port="5000"
timeout="1200"
num_threads="1"

gunicorn_ssl_options=
if [ -n "${TLS_CERTIFICATE}" ] && [ -n "${TLS_KEY}" ]; then
    gunicorn_ssl_options="--keyfile ${TLS_KEY} --certfile ${TLS_CERTIFICATE}"
    server_port="5443"
fi

exec gunicorn --log-config ${logging_file_config} --access-logfile - \
  --workers ${num_workers} \
  -t ${timeout} \
  --threads ${num_threads} \
  --bind "0.0.0.0:${server_port}" ${gunicorn_ssl_options} \
  geoprofile.app:app
