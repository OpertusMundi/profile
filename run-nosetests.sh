#!/bin/sh
#set -x
set -e

export FLASK_APP="geoprofile"
export SECRET_KEY="$(dd if=/dev/urandom bs=12 count=1 status=none | base64)"

if [ -f "${DB_PASS_FILE}" ]; then
    DB_PASS="$(cat ${DB_PASS_FILE})"
fi
export DATABASE_URI="${DB_ENGINE}://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

# Initialize database

flask init-db

# Run

exec nosetests $@
