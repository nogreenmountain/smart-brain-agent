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

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
