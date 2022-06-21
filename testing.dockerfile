FROM osgeo/gdal:ubuntu-full-3.1.0 as build-stage-1

RUN apt-get update \
    && apt-get install -y gcc make g++ git python3-pip \
    && pip3 install --upgrade pip

RUN pip3 install --upgrade pip \
    && pip3 install --prefix=/usr/local "pycld2==0.41"

RUN pip3 install --prefix=/usr/local \
    git+https://github.com/OpertusMundi/geovaex.git@v0.3.3 \
    git+https://github.com/OpertusMundi/BigDataVoyant.git@v1.2.9


FROM osgeo/gdal:ubuntu-full-3.1.0
ARG VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip libicu-dev python3-icu

ENV VERSION="${VERSION}"
ENV PYTHON_VERSION="3.8"
ENV PYTHONPATH="/usr/local/lib/python${PYTHON_VERSION}/site-packages"

RUN groupadd flask \
    && useradd -m -d /var/local/geoprofile -g flask flask

COPY --from=build-stage-1 /usr/local/ /usr/local/

RUN pip3 install --upgrade pip
COPY requirements.txt requirements-testing.txt ./
RUN pip3 install --prefix=/usr/local -r requirements.txt -r requirements-testing.txt
RUN python -c "import nltk; nltk.download('punkt', '/usr/local/share/nltk_data')"

ENV FLASK_APP="geoprofile" \
    FLASK_ENV="testing" \
    FLASK_DEBUG="false" \
    INPUT_DIR="./input" \
    OUTPUT_DIR="./output"

COPY run-nosetests.sh /
RUN chmod a+x /run-nosetests.sh
ENTRYPOINT ["/run-nosetests.sh"]
