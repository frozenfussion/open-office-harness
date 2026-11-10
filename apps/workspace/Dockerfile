# SPDX-License-Identifier: AGPL-3.0-only
FROM node:26.13.0-bookworm-slim AS build
WORKDIR /build/apps/workspace
COPY apps/workspace/package.json apps/workspace/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/design-system /build/apps/design-system
COPY apps/workspace .
RUN npx ng build

FROM nginxinc/nginx-unprivileged:1.28.0-alpine
COPY apps/workspace/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/apps/workspace/dist/workspace/browser /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
