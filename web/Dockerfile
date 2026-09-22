FROM node:24-bookworm-slim AS base

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN corepack enable

FROM base AS build

WORKDIR /app/web

COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/.npmrc ./
COPY web/patches ./patches
RUN pnpm install --frozen-lockfile

COPY web .
COPY config /app/config

RUN pnpm exec svelte-kit sync && pnpm build && pnpm prune --prod --ignore-scripts

FROM base AS runtime

WORKDIR /app

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000

COPY --from=build --chown=node:node /app/web/build ./build
COPY --from=build --chown=node:node /app/web/package.json ./package.json
COPY --from=build --chown=node:node /app/web/node-server.mjs ./node-server.mjs
COPY --from=build --chown=node:node /app/web/node_modules ./node_modules

RUN mkdir -p /data && chown node:node /data

USER node
WORKDIR /data

EXPOSE 3000

CMD ["node", "/app/node-server.mjs"]
