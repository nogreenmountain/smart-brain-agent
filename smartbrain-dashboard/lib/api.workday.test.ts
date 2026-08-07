import { afterEach, describe, expect, it, vi } from 'vitest';

import { getCCSwitchUsageSyncStatus, getWorkdaySummary, WorkdaySummary } from './api';

const response: WorkdaySummary = {
  status: 'no_data',
  project_id: 'project-1',
  employee: { id: 'employee/a b', name: 'employee/a b' },
  date: '2026-07-20',
  timezone: 'Asia/Shanghai',
  overview: {
    active_start: null,
    active_end: null,
    active_time_range_seconds: 0,
    trace_count: 0,
    span_count: 0,
    task_count: 0,
    llm_call_count: 0,
    tool_call_count: 0,
    error_count: 0,
    total_tokens: 0,
    total_cost: 0,
    avg_llm_latency_ms: 0,
    p95_llm_latency_ms: 0,
  },
  narrative_summary: '',
  tasks: [],
  findings: [],
  important_traces: [],
  distillation_candidates: [],
  raw_metrics: null,
  warnings: [],
};

describe('getWorkdaySummary', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('serializes the workday filters and include switches', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await getWorkdaySummary('project-1', {
      employeeId: 'employee/a b',
      date: '2026-07-20',
      includeTraces: false,
      includeReplayRefs: true,
      includeRawMetrics: false,
    });

    expect(result).toEqual(response);
    expect(fetchMock).toHaveBeenCalledOnce();

    const [requestUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const url = new URL(requestUrl);
    expect(url.pathname).toBe('/v4/workday/summary/project-1');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      employee_id: 'employee/a b',
      date: '2026-07-20',
      include_traces: 'false',
      include_replay_refs: 'true',
      include_raw_metrics: 'false',
    });
    expect(init.credentials).toBe('include');
  });
});

describe('getCCSwitchUsageSyncStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('queries the current user sync result by manual request id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        status: 'ok',
        employee_id: 'test1',
        employee_name: 'Test 1',
        request_id: '11111111-1111-1111-1111-111111111111',
        total_tokens: 40000000,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getCCSwitchUsageSyncStatus('11111111-1111-1111-1111-111111111111');

    const [requestUrl] = fetchMock.mock.calls[0] as [string, RequestInit];
    const url = new URL(requestUrl);
    expect(url.pathname).toBe('/v4/ai-usage/cc-switch-sync/status');
    expect(url.searchParams.get('request_id')).toBe('11111111-1111-1111-1111-111111111111');
  });
});
