# ---- build stage ----
FROM node:24.18.0-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- serve stage ----
FROM nginx:1.29.8-alpine

# Serve the built SPA on :3000 with history-API fallback so client-side routes
# (e.g. /painting/shelf) resolve to index.html instead of 404ing. The outer
# proxy service still handles /api → backend, so no API config is baked in here.
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000
