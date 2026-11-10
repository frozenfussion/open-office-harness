# SPDX-License-Identifier: AGPL-3.0-only
FROM node:26.13.0-bookworm-slim AS build
WORKDIR /build/apps/admin-console
COPY apps/admin-console/package*.json apps/admin-console/copy-design.mjs ./
COPY apps/design-system /build/apps/design-system
RUN npm ci
COPY apps/admin-console/angular.json apps/admin-console/tsconfig*.json ./
COPY apps/admin-console/src ./src
RUN npm run build
FROM nginxinc/nginx-unprivileged:1.28.0-alpine
COPY apps/admin-console/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/apps/admin-console/dist/admin-console/browser /usr/share/nginx/html
USER 101
EXPOSE 8080
