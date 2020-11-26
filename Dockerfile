FROM osgeo/gdal:alpine-normal-3.1.0 as build-stage-1


RUN apk add --no-cache --update python3 python3-dev gcc gfortran musl-dev g++ libffi-dev openssl-dev \
    libxml2 libxml2-dev libxslt libxslt-dev libjpeg-turbo-dev zlib-dev git
RUN pip3 install --upgrade cython
RUN pip3 install --upgrade pip
RUN pip3 install --prefix=/usr/local git+https://github.com/OpertusMundi/geovaex.git
RUN pip3 install --prefix=/usr/local git+https://github.com/OpertusMundi/BigDataVoyant.git

FROM osgeo/gdal:alpine-normal-3.1.0
ARG VERSION

LABEL language="python"
LABEL framework="flask"
LABEL usage="profile microservice for rasters and vectors"

RUN apk update && apk add --no-cache sqlite py3-yaml py3-numpy

ENV VERSION="${VERSION}"
ENV PYTHON_VERSION="3.8"
ENV PYTHONPATH="/usr/local/lib/python${PYTHON_VERSION}/site-packages"

RUN addgroup flask && adduser -h /var/local/geoprofile -D -G flask flask

COPY --from=build-stage-1 /usr/local/ /usr/local

RUN pip3 install --upgrade pip

RUN mkdir /usr/local/geoprofile/
COPY setup.py requirements.txt requirements-production.txt /usr/local/geoprofile/
COPY geoprofile /usr/local/geoprofile/geoprofile

RUN cd /usr/local/geoprofile && pip3 install --prefix=/usr/local -r requirements.txt -r requirements-production.txt
RUN cd /usr/local/geoprofile && python setup.py install --prefix=/usr/local

WORKDIR /usr/local/geoprofile

COPY wsgi.py docker-command.sh /usr/local/bin/
RUN chmod a+x /usr/local/bin/wsgi.py /usr/local/bin/docker-command.sh

WORKDIR /var/local/geoprofile
RUN mkdir ./logs && chown flask:flask ./logs
COPY --chown=flask logging.conf .

ENV FLASK_ENV="production" FLASK_DEBUG="false"
ENV OUTPUT_DIR="/var/local/geoprofile/output/" SECRET_KEY_FILE="/var/local/geoprofile/secret_key"
ENV TLS_CERTIFICATE="" TLS_KEY=""

USER flask
CMD ["/usr/local/bin/docker-command.sh"]

EXPOSE 5000
EXPOSE 5443