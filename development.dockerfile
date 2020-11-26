FROM osgeo/gdal:ubuntu-full-3.1.0 as build-stage-1

RUN apt-get update && apt-get install -y gcc make g++ git python3-pip git
RUN pip3 install --upgrade pip
RUN pip3 install --user --no-warn-script-location git+https://github.com/OpertusMundi/geovaex.git
RUN pip3 install --user --no-warn-script-location git+https://github.com/OpertusMundi/BigDataVoyant.git

FROM osgeo/gdal:ubuntu-full-3.1.0

LABEL language="python"
LABEL framework="flask"
LABEL usage="profile microservice for rasters and vectors"

RUN apt-get update && apt-get install -y --no-install-recommends sqlite python3-pip gunicorn

COPY --from=build-stage-1 /root/.local /root/.local

RUN mkdir /usr/local/geoprofile/
COPY setup.py requirements.txt /usr/local/geoprofile/
COPY geoprofile /usr/local/geoprofile/geoprofile

WORKDIR /usr/local/geoprofile

RUN pip3 install --no-cache-dir --upgrade pip

RUN pip3 install --no-cache-dir --user --no-warn-script-location -r requirements.txt

RUN python setup.py install --user

COPY wsgi.py docker-command-dev.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/wsgi.py /usr/local/bin/docker-command-dev.sh

EXPOSE 5000
EXPOSE 5443

ENV FLASK_ENV="production" FLASK_DEBUG="false"
ENV OUTPUT_DIR="/var/local/geoprofile/output/"
ENV TLS_CERTIFICATE="" TLS_KEY=""

CMD ["/usr/local/bin/docker-command-dev.sh"]