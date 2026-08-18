# Builder stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package manifest
COPY package*.json ./

# Install dependencies (offline-friendly: cache is mounted)
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# Copy project files
COPY . .

# Build. Do not bake NEXT_PUBLIC_API_URL into client chunks; the browser
# derives the API host from the current dashboard hostname at runtime.
RUN npm run build

# Runtime stage
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production

COPY --chown=node:node --from=builder /app/.next/standalone ./
COPY --chown=node:node --from=builder /app/.next/static ./.next/static
COPY --chown=node:node --from=builder /app/public ./public

RUN mkdir -p /app/.next/cache && chown node:node /app/.next/cache

USER node

EXPOSE 3000
CMD ["node", "server.js"]
