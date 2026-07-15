FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY docker-entrypoint.d/05-ensure-tls-certificate.sh /docker-entrypoint.d/05-ensure-tls-certificate.sh

RUN chmod +x /docker-entrypoint.d/05-ensure-tls-certificate.sh
