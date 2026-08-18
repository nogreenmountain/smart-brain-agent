/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  outputFileTracingRoot: __dirname,
  // api.ts 是 client-only,不要在 server build 阶段拉它
  serverExternalPackages: [],
};

module.exports = nextConfig;
