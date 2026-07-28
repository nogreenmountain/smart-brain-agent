import { afterEach, describe, expect, it, vi } from 'vitest';

import { getWorkdaySummary, login } from './api';

describe('login', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('maps a local username to its local.dev email account', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ success: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            user_id: 'user-1',
            email: 'test1@local.dev',
            full_name: 'test1',
            avatar_url: null,
            memberships: [],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      );
    vi.stubGlobal('fetch', fetchMock);

    await login(' test1 ', '123456');

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      email: 'test1@local.dev',
      password: '123456',
    });
  });
});

describe('getWorkdaySummary', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the employee, date, and privacy include flags', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'no_data',
          project_id: 'project/one',
          employee: { id: 'employee-001', name: 'employee-001' },
          date: '2026-07-20',
          timezone: 'Asia/Shanghai',
          overview: {},
          narrative_summary: '',
          tasks: [],
          findings: [],
          important_traces: [],
          distillation_candidates: [],
          raw_metrics: null,
          warnings: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getWorkdaySummary('project/one', {
      employeeId: 'employee-001',
      date: '2026-07-20',
      includeTraces: false,
      includeReplayRefs: false,
      includeRawMetrics: true,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      'http://localhost:8000/v4/workday/summary/project%2Fone?' +
        'employee_id=employee-001&date=2026-07-20&include_traces=false&' +
        'include_replay_refs=false&include_raw_metrics=true',
    );
    expect(init).toMatchObject({ credentials: 'include' });
  });
});
