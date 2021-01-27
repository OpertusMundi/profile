FROM osgeo/gdal:ubuntu-full-3.1.0 as build-stage-1

RUN apt-get update \
    && apt-get install -y gcc make g++ git python3-pip \
    && pip3 install --upgrade pip

RUN pip3 install --prefix=/usr/local \
    git+https://github.com/OpertusMundi/geovaex.git@v0.1.0 \
    git+https://github.com/OpertusMundi/BigDataVoyant.git@v1.2.0


FROM osgeo/gdal:ubuntu-full-3.1.0
ARG VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite python3-pip

ENV VERSION="${VERSION}"
ENV PYTHON_VERSION="3.8"
ENV PYTHONPATH="/usr/local/lib/python${PYTHON_VERSION}/site-packages"

COPY --from=build-stage-1 /usr/local/ /usr/local/

RUN pip3 install --upgrade pip
COPY requirements.txt requirements-testing.txt ./
RUN pip3 install --prefix=/usr/local -r requirements.txt -r requirements-testing.txt

# Get permission for vaex's private files so that the Setup/Teardown does not fail due to insufficient permissions
RUN mkdir -p /.vaex/data \
    && chmod o+r /.vaex/data \
    && touch /.vaex/main.yml \
    && chmod o+r /.vaex/main.yml \
    && touch /.vaex/webclient.yml \
    && chmod o+r /.vaex/webclient.yml \
    && touch /.vaex/webserver.yml \
    && chmod o+r /.vaex/webserver.yml \
    && touch /.vaex/cluster.yml \
    && chmod o+r /.vaex/cluster.yml

ENV FLASK_APP="geoprofile" \
    FLASK_ENV="testing" \
    FLASK_DEBUG="false" \
    OUTPUT_DIR="./output"

COPY run-nosetests.sh /
RUN chmod a+x /run-nosetests.sh
ENTRYPOINT ["/run-nosetests.sh"]
