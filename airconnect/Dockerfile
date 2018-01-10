FROM debian:jessie
# Setup base system
RUN \
    apt-get update \
    \
    && apt-get install -y --no-install-recommends libssl1.0.0 wget ca-certificates \
    \
    && rm -f -r \
        /tmp/* \
        /var/lib/apt/lists/*
RUN wget https://raw.githubusercontent.com/philippe44/AirConnect/master/bin/airupnp-x86-64 \
    && chmod 755 airupnp-x86-64
ENTRYPOINT [ “./airupnp-x86-64” ]
