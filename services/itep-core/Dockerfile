FROM node:22-alpine AS build
WORKDIR /app
ARG NPM_STRICT_SSL=true
ARG NODE_TLS_REJECT_UNAUTHORIZED
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm_config_strict_ssl="${NPM_STRICT_SSL}" \
    NODE_TLS_REJECT_UNAUTHORIZED="${NODE_TLS_REJECT_UNAUTHORIZED}" \
    npm ci --no-audit --no-fund
COPY . .
RUN NODE_TLS_REJECT_UNAUTHORIZED="${NODE_TLS_REJECT_UNAUTHORIZED}" \
    npm run prisma:generate \
    && npm run build

FROM build AS production-deps
RUN npm prune --omit=dev --no-audit --no-fund

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
COPY --from=production-deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/prisma ./prisma
RUN chown -R node:node /app
USER node
EXPOSE 3000
CMD ["node", "dist/src/api/main.js"]
