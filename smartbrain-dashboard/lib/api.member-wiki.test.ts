import { afterEach, describe, expect, it, vi } from 'vitest';

import { getMemberWikiOptions, getMemberWikiOverview } from './api';

describe('member Wiki API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads privacy-scoped member options', async () => {
    const payload = {
      mode: 'self',
      current_member: { user_id: 'u1', employee_id: 'test1', name: '张三', email: 'test1@local.dev' },
      members: [{ user_id: 'u1', employee_id: 'test1', name: '张三', email: 'test1@local.dev' }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    expect(await getMemberWikiOptions()).toEqual(payload);
    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe('/v4/member-wiki/options');
  });

  it('serializes member and reusable-experience filters', async () => {
    const payload = {
      mode: 'admin',
      member: { user_id: 'u1', employee_id: 'test1', name: '张三', email: 'test1@local.dev' },
      timezone: 'Asia/Shanghai',
      summary: { experience_count: 0, success_count: 0, failure_count: 0, latest_observed: null },
      experiences: [],
      latest_run: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await getMemberWikiOverview({
      employeeId: 'test1', query: '部署新版本', taskType: 'deployment',
      outcome: 'success', tag: 'docker', limit: 30,
    });

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe('/v4/member-wiki/overview');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      employee_id: 'test1', query: '部署新版本', task_type: 'deployment',
      outcome: 'success', tag: 'docker', limit: '30',
    });
  });
});
