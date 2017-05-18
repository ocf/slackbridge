FROM docker.ocf.berkeley.edu/theocf/debian:stretch

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        cracklib-runtime \
        libcrack2-dev \
        libffi-dev \
        libssl-dev \
        python3 \
        python3-dev \
        python3-pip \
        runit \
        virtualenv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN install -d --owner=nobody /opt/slackbridge /opt/slackbridge/venv

COPY requirements.txt /opt/slackbridge/
RUN virtualenv -ppython3 /opt/slackbridge/venv \
    && /opt/slackbridge/venv/bin/pip install pip==9.0.1 \
    && /opt/slackbridge/venv/bin/pip install \
        -r /opt/slackbridge/requirements.txt

COPY services /opt/slackbridge/services
RUN chown -R nobody:nogroup /opt/slackbridge

COPY slackbridge.py /opt/slackbridge/
RUN chown nobody:nogroup /opt/slackbridge/slackbridge.py

USER nobody

WORKDIR /opt/slackbridge

CMD ["runsvdir", "/opt/slackbridge/services"]
