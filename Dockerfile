FROM python:3.12-slim

RUN pip install --no-cache-dir getnit

WORKDIR /workspace
VOLUME ["/workspace"]

ENTRYPOINT ["nit"]
