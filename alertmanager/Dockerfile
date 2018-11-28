FROM prom/alertmanager

ARG slack_channel
ARG slack_webhook_url

COPY config.yml /etc/alertmanager/config.yml

RUN sed -i -e "s=%%slack_channel%%=$slack_channel=" \
  -e "s=%%slack_webhook_url%%=$slack_webhook_url=" \
  /etc/alertmanager/config.yml

#RUN cat /etc/alertmanager/config.yml
