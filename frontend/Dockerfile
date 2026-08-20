# Node 24 (Krypton), active LTS until 2028-04-30.
#
# This said node:20 from the first public commit and nobody revisited it. Node
# 20 reached end of life on 2026-04-30, so the image serving production went
# four months without security patches — and V8's own wording changes between
# majors, which shipped a JSON-error reader that only worked on the author's
# machine (see src/lib/json-error.ts). CI pins the same major.
FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM base AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1

EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
# Baked into Next.js rewrites at build time — points at the Docker service.
ARG API_PROXY_URL=http://localhost:8001
ENV API_PROXY_URL=${API_PROXY_URL}
RUN npm run build

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Use 127.0.0.1 (not localhost): the server binds IPv4 0.0.0.0, but `localhost`
# resolves to IPv6 ::1 first inside the container → wget gets "connection refused"
# and the container is wrongly marked unhealthy while it serves fine.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget --spider -q http://127.0.0.1:3000/en || exit 1

CMD ["node", "server.js"]
