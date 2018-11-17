FROM nginx

RUN apt-get update && apt-get install openssl


ARG external_hostname
ARG internal_hostname

COPY nginx.conf /etc/nginx/nginx.conf

RUN sed -i -e "s/%%external_hostname%%/$external_hostname/" \
  -e "s/%%internal_hostname%%/$internal_hostname/" \
  /etc/nginx/nginx.conf
