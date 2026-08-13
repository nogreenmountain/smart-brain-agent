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

    const file = new File(['会议全文'], 'meeting.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    await createMeetingSummary({
      projectId: 'project-1', title: '周会', meetingDate: '2026-08-05',
      participantUserIds: ['user-1', 'user-2'], file,
    });

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/v4/meeting-summaries'), expect.objectContaining({
      method: 'POST', body: expect.any(FormData),
    }));
    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(JSON.parse(String(form.get('participant_user_ids')))).toEqual(['user-1', 'user-2']);
    expect(form.get('file')).toBe(file);
    expect(form.has('tags')).toBe(false);
    expect(form.has('summary')).toBe(false);
    expect(form.has('decisions')).toBe(false);
    expect(form.has('action_items')).toBe(false);
  });
});
