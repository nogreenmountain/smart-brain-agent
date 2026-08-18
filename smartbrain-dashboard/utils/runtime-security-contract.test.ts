import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const dashboardRoot = process.cwd();
const appRoot = resolve(dashboardRoot, '..');

describe('SmartBrain production runtime security contract', () => {
  it('uses the patched Next.js release required after the React Flight RCE', () => {
    const packageJson = JSON.parse(
      readFileSync(`${dashboardRoot}/package.json`, 'utf8'),
    ) as { dependencies: { next: string } };

    expect(packageJson.dependencies.next).toBe('15.5.23');
  });

  it('pins standalone tracing to the SmartBrain app instead of the parent workspace', () => {
    const nextConfig = readFileSync(`${dashboardRoot}/next.config.js`, 'utf8');

    expect(nextConfig).toContain('outputFileTracingRoot: __dirname');
  });

  it.each(['Dockerfile', 'Dockerfile.runtime-local'])(
    'runs %s as the unprivileged node user',
    (dockerfileName) => {
      const dockerfile = readFileSync(
        `${dashboardRoot}/${dockerfileName}`,
        'utf8',
      );

      expect(dockerfile).toContain('COPY --chown=node:node');
      expect(dockerfile).toContain('USER node');
    },
  );

  it('includes only the current standalone build in the runtime-local context', () => {
    const dockerignore = readFileSync(
      `${dashboardRoot}/Dockerfile.runtime-local.dockerignore`,
      'utf8',
    );

    expect(dockerignore).toContain('.next.pre-*');
    expect(dockerignore).not.toMatch(/^\.next\*?$/m);
  });

  it('hardens the deployed SmartBrain container filesystem and privileges', () => {
    const compose = readFileSync(`${appRoot}/compose.server.override.yaml`, 'utf8');
    const smartbrainService = compose.match(
      /\n  smartbrain:\n([\s\S]*?)(?=\nvolumes:)/,
    )?.[1];

    expect(smartbrainService).toBeDefined();
    expect(smartbrainService).toContain('read_only: true');
    expect(smartbrainService).toContain('no-new-privileges:true');
    expect(smartbrainService).toContain('cap_drop:');
    expect(smartbrainService).toContain('- ALL');
    expect(smartbrainService).toContain('/tmp:rw,noexec,nosuid,nodev');
    expect(smartbrainService).toContain('/app/.next/cache:rw,nosuid,nodev');
  });
});
