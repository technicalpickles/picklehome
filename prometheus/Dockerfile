FROM prom/prometheus

COPY prometheus.yml /etc/prometheus/prometheus/prometheus.yml

RUN sed -i -e "s/%%bearer_token%%/$bearer_token/" \
  /etc/prometheus/prometheus.yml
