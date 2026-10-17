FROM node:24.22.0-alpine3.24 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.30.6-alpine3.24
COPY frontend/nginx.conf /etc/nginx/nginx.conf.template
COPY --chmod=755 frontend/start-web /usr/local/bin/start-web
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start-web"]
CMD ["-g", "daemon off;"]
