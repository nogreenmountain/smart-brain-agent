type BrowserLocation = Pick<Location, 'protocol' | 'hostname' | 'port' | 'origin'>;

function usesSharedHttpsRelay(location: BrowserLocation): boolean {
  return location.protocol === 'https:' && (location.port === '' || location.port === '443');
}

export function apiBaseForLocation(location: BrowserLocation): string {
  if (usesSharedHttpsRelay(location)) return location.origin;
  return `${location.protocol}//${location.hostname}:8000`;
}

export function mcpEndpointForLocation(location: BrowserLocation): string {
  if (usesSharedHttpsRelay(location)) return `${location.origin}/mcp`;
  return `${location.protocol}//${location.hostname}:8010/mcp`;
}

export function traceReplayForLocation(location: BrowserLocation, traceId: string): string {
  const path = `/traces?trace_id=${encodeURIComponent(traceId)}`;
  if (usesSharedHttpsRelay(location)) return `${location.origin}${path}`;
  return `${location.protocol}//${location.hostname}:3001${path}`;
}
