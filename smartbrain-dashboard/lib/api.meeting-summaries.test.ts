import { afterEach, describe, expect, it, vi } from 'vitest';

import { createMeetingSummary, listMeetingSummaries } from './api';

describe('meeting summaries API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('serializes project search filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await listMeetingSummaries({ projectId: 'project-1', query: 'MCP', tag: '周会' });

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe('/v4/meeting-summaries');
    expect(Object.fromEntries(url.searchParams)).toEqual({ project_id: 'project-1', query: 'MCP', tag: '周会' });
  });

  it('uploads meeting summary as multipart form data', async () => {
    const payload = { id: 'meeting-1', title: '周会' };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await createMeetingSummary({
      projectId: 'project-1', title: '周会', meetingDate: '2026-08-05', participants: '张三',
      tags: '周会', summary: '摘要', decisions: '决定', actionItems: '行动项', file: null,
    });

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/v4/meeting-summaries'), expect.objectContaining({
      method: 'POST', body: expect.any(FormData),
    }));
  });
});
