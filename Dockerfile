FROM python:3.12-alpine AS build
WORKDIR /src
COPY tools/build_web_player.py tools/
COPY web/player/ web/player/
COPY mariana/ mariana/
COPY desktop/culture_sources.json desktop/
COPY res/ res/
ARG MARIANA_SPOTIFY_WEB_CLIENT_ID
ARG MARIANA_SNAPCHAT_WEB_CLIENT_ID
ARG MARIANA_JITSI_ORIGIN
RUN python tools/build_web_player.py --output /srv/player

FROM nginxinc/nginx-unprivileged:stable-alpine AS web
COPY packaging/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /srv/player /usr/share/nginx/html
COPY LICENSE /usr/share/nginx/html/LICENSE
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
