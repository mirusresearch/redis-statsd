FROM python:3.7

COPY . /usr/src/app
WORKDIR /usr/src/app

RUN pip install -r pip.requirements.txt
