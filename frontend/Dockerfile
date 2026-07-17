# ---- build stage ----
FROM node:26.5.0-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- serve stage ----
FROM nginx:1.31.2-alpine

# Serve the SPA on :3000 AND reverse-proxy /api → the backend, so the frontend
# container is a self-contained entry point (no separate proxy service needed).
# The backend address is a runtime variable: the nginx image envsubst's
# /etc/nginx/templates/*.template into /etc/nginx/conf.d/ at container start.
# Override BACKEND_ORIGIN to match your backend's service/host (default suits
# the repo's docker-compose service name).
ENV BACKEND_ORIGIN=http://backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000
