FROM nginx:1.27-alpine

RUN apk add --no-cache openssl tzdata \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

ENV TZ=Asia/Shanghai

COPY docker-entrypoint.d/05-ensure-tls-certificate.sh /docker-entrypoint.d/05-ensure-tls-certificate.sh

RUN chmod +x /docker-entrypoint.d/05-ensure-tls-certificate.sh
