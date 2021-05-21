FROM python:3.9.1-alpine3.12 as base

RUN apk add --update \
    tzdata

FROM python:3.9.1-alpine3.12

WORKDIR /home/omnik/source
ADD requirements.txt omnikloggerproxy.py omnikdataloggerproxy.service config.ini_example.txt config.yaml_example.txt \
  omnikproxy_example_startup.sh iptables_setup_example.sh setup.py README.md /home/omnik/source/

COPY --from=base /usr/share/zoneinfo /usr/share/zoneinfo

ENV TZ=Europe/Amsterdam

RUN pip3 install -r requirements.txt --upgrade && \
  adduser -D -u 1000 omnik && \
  python3 setup.py install

WORKDIR /home/omnik
USER omnik

EXPOSE 10004

ENTRYPOINT ["omnikloggerproxy.py"]

CMD ["--settings", "/config.yaml", "--config", "/config.ini"]
