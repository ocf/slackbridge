FROM docker.ocf.berkeley.edu/theocf/debian:stretch

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        cracklib-runtime \
        libcrack2-dev \
        libffi-dev \
        libssl-dev \
        python3.7-dev \
        virtualenv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN install -d --owner=nobody /opt/slackbridge /opt/slackbridge/venv

COPY requirements.txt /opt/slackbridge/
RUN virtualenv -ppython3.7 /opt/slackbridge/venv \
    && /opt/slackbridge/venv/bin/pip install pip==9.0.1 \
    && /opt/slackbridge/venv/bin/pip install \
        -r /opt/slackbridge/requirements.txt

RUN chown -R nobody:nogroup /opt/slackbridge

# Run these separate from the chown before so that when developing the docker
# cached layers makes rebuilding faster since it doesn't have to chown the whole
# project again (including vendored stuff)
COPY slackbridge /opt/slackbridge/slackbridge
RUN chown -R nobody:nogroup /opt/slackbridge/slackbridge

USER nobody

WORKDIR /opt/slackbridge
CMD ["/opt/slackbridge/venv/bin/python", "-m", "slackbridge.main"]
