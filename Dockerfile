FROM alpine:3.12

# Install python/pip
ENV PYTHONUNBUFFERED=1
RUN apk add --update --no-cache git libxml2 libxslt-dev gcc musl-dev libffi-dev libmagic
RUN apk add --update --no-cache python3~3.8 python3-dev~3.8 && ln -sf python3 /usr/bin/python
RUN python3 -m ensurepip
RUN pip3 install --no-cache --upgrade pip setuptools

# Preparations for PCF
RUN mkdir /pcf
ADD . /pcf
WORKDIR /pcf

# Add dependencies
RUN pip3 install --no-cache --upgrade -r requirements_unix.txt

# run PCF
ENTRYPOINT pip3 install -r requirements_unix.txt; if [ ! -e "./configuration/database.sqlite3" ]; then echo 'DELETE_ALL' | python3 new_initiation.py; fi && python3 run.py