import { describe, expect, it } from 'vitest';

import { apiBaseForLocation, mcpEndpointForLocation, traceReplayForLocation } from './service-endpoints';

describe('public service endpoints', () => {
  it('reuses standard HTTPS origin for the public IP relay', () => {
    const location = new URL('https://39.105.79.0/wiki');

    expect(apiBaseForLocation(location)).toBe('https://39.105.79.0');
    expect(mcpEndpointForLocation(location)).toBe('https://39.105.79.0/mcp');
    expect(traceReplayForLocation(location, 'trace 1')).toBe(
      'https://39.105.79.0/traces?trace_id=trace%201',
    );
  });

  it('preserves the existing LAN development ports', () => {
    const location = new URL('http://192.168.1.40:3002/wiki');

    expect(apiBaseForLocation(location)).toBe('http://192.168.1.40:8000');
    expect(mcpEndpointForLocation(location)).toBe('http://192.168.1.40:8010/mcp');
    expect(traceReplayForLocation(location, 'abc')).toBe(
      'http://192.168.1.40:3001/traces?trace_id=abc',
    );
  });
});
