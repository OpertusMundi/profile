FROM osgeo/gdal:ubuntu-full-3.1.0 as build-stage-1

RUN apt-get update \
    && apt-get install -y gcc make g++ git python3-pip \
    && pip3 install --upgrade pip

RUN pip3 install --upgrade pip \
    && pip3 install --prefix=/usr/local "pycld2==0.41"

RUN pip3 install --prefix=/usr/local \
    git+https://github.com/OpertusMundi/geovaex.git@v0.3.6 \
    git+https://github.com/OpertusMundi/BigDataVoyant.git@v2.0.15

FROM osgeo/gdal:ubuntu-full-3.1.0
ARG VERSION

LABEL language="python"
LABEL framework="flask"
LABEL usage="profile microservice for rasters and vectors"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip libicu-dev python3-icu

ENV VERSION="${VERSION}"
ENV PYTHON_VERSION="3.8"
ENV PYTHONPATH="/usr/local/lib/python${PYTHON_VERSION}/site-packages"

RUN groupadd flask \
    && useradd -m -d /var/local/geoprofile -g flask flask

COPY --from=build-stage-1 /usr/local/ /usr/local/

RUN pip3 install --upgrade pip

RUN mkdir /usr/local/geoprofile/
COPY setup.py requirements.txt requirements-production.txt /usr/local/geoprofile/
COPY geoprofile /usr/local/geoprofile/geoprofile

RUN cd /usr/local/geoprofile \
    && pip3 install --prefix=/usr/local -r requirements.txt -r requirements-production.txt \
    && python setup.py install --prefix=/usr/local

RUN python -c "import nltk; nltk.download('punkt', '/usr/local/share/nltk_data')"

COPY wsgi.py docker-command.sh /usr/local/bin/
RUN chmod a+x /usr/local/bin/wsgi.py /usr/local/bin/docker-command.sh

WORKDIR /var/local/geoprofile
RUN mkdir ./logs \
    && chown flask:flask ./logs
COPY --chown=flask logging.conf .

ENV FLASK_APP="geoprofile" \
    FLASK_ENV="production" \
    FLASK_DEBUG="false" \
    LOGGING_ROOT_LEVEL="" \
    INSTANCE_PATH="/var/local/geoprofile/data/" \
    SCHEMATA_PATH="/usr/local/geoprofile/geoprofile/schemata" \
    INPUT_DIR="/var/local/geoprofile/input/" \
    OUTPUT_DIR="/var/local/geoprofile/output/" \
    SECRET_KEY_FILE="/var/local/geoprofile/secret_key" \
    TLS_CERTIFICATE="" \
    TLS_KEY=""

USER flask
CMD ["/usr/local/bin/docker-command.sh"]

EXPOSE 5000
EXPOSE 5443
