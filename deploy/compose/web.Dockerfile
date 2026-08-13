ARG NODE_IMAGE=node:22.22.0-alpine
ARG NGINX_IMAGE=nginx:1.27.0-alpine
FROM ${NODE_IMAGE} AS web-dependencies

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm config set replace-registry-host always \
    && npm ci

FROM web-dependencies AS web-quality
COPY apps/web ./apps/web
COPY tests/e2e ./tests/e2e

FROM web-quality AS web-build
RUN npm run build --workspace @aiops-x/web

FROM ${NGINX_IMAGE} AS web-runtime
COPY deploy/compose/web-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 8080

FROM mcr.microsoft.com/playwright:v1.62.1-noble AS web-e2e
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web ./apps/web
COPY tests/e2e ./tests/e2e
