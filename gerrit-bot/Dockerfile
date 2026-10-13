FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 bot \
    && mkdir /data \
    && chown bot /data

COPY precheck_submit_bot.py entrypoint.sh /app/

USER bot
VOLUME /data
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--state", "/data/state.json"]
