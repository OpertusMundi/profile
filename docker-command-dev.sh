#!/bin/sh
set -e
set -x

if [ -z "${OUTPUT_DIR}" ]; then
    echo "OUTPUT_DIR is not set!" 1>&2
    exit 1
fi

# Initialize database

export FLASK_APP="geoprofile"
export DATABASE="./geoprofile.sqlite"

~/.local/bin/flask init-db

# Configure and start WSGI server

if [ "${FLASK_ENV}" == "development" ]; then
    exec ~/.local/bin/flask run
fi

num_workers="4"
server_port="5000"
gunicorn_ssl_options=
if [ -n "${TLS_CERTIFICATE}" ] && [ -n "${TLS_KEY}" ]; then
    gunicorn_ssl_options="--keyfile ${TLS_KEY} --certfile ${TLS_CERTIFICATE}"
    server_port="5443"
fi

exec gunicorn --workers ${num_workers} --bind "0.0.0.0:${server_port}" ${gunicorn_ssl_options} geoprofile.app:app