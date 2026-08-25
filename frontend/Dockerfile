# =============================================================================
# TransformIQ Frontend — Dockerfile
# =============================================================================
FROM node:20-alpine AS base

# ---------------------------------------------------------------------------
# Dependencies stage
# ---------------------------------------------------------------------------
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json package-lock.json* ./
# Use npm install (not npm ci) to handle lock file version differences
# between development environments.
RUN npm install

# ---------------------------------------------------------------------------
# Development stage (used by docker-compose for local dev with hot reload)
# ---------------------------------------------------------------------------
FROM base AS development
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------------------
# Builder stage (for production builds)
# ---------------------------------------------------------------------------
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build args for public env vars baked at build time
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

# ---------------------------------------------------------------------------
# Production runner stage
# ---------------------------------------------------------------------------
FROM base AS production
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT 3000
CMD ["node", "server.js"]
