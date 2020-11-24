FROM osgeo/gdal:alpine-normal-3.1.0 as build-stage-1

RUN apk update && apk add gcc make cmake g++ musl-dev python3-dev libffi-dev git
RUN pip3 install --upgrade pip
RUN pip3 install --user "pyproj>=2.6.0,<2.7.0"
RUN pip3 install --user git+https://github.com/OpertusMundi/geovaex.git
RUN pip3 install --user git+https://github.com/OpertusMundi/BigDataVoyant.git

FROM osgeo/gdal:alpine-normal-3.1.0

LABEL language="python"
LABEL framework="flask"
LABEL usage="profile microservice for rasters and vectors"

RUN apk update && apk add --no-cache sqlite py3-yaml py3-gunicorn git py3-numpy

COPY --from=build-stage-1 /root/.local /root/.local

RUN mkdir /usr/local/geoprofile/
COPY setup.py requirements.txt /usr/local/geoprofile/
COPY geoprofile /usr/local/geoprofile/geoprofile

WORKDIR /usr/local/geoprofile

RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir --user --no-warn-script-location -r requirements.txt

RUN python setup.py install --user

COPY wsgi.py docker-command.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/wsgi.py /usr/local/bin/docker-command.sh

EXPOSE 5000
EXPOSE 5443

ENV FLASK_APP="geoprofile" FLASK_ENV="production" FLASK_DEBUG="false"
ENV OUTPUT_DIR="/var/local/geoprofile/output/"
ENV TLS_CERTIFICATE="" TLS_KEY=""

CMD ["/usr/local/bin/docker-command.sh"]