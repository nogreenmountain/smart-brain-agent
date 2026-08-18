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

  it('reports multipart upload bytes and the server-processing phase', async () => {
    const progress = vi.fn();
    class FakeXMLHttpRequest {
      static instance: FakeXMLHttpRequest;
      upload = { onprogress: null as ((event: ProgressEvent) => void) | null, onload: null as (() => void) | null };
      status = 200;
      responseText = JSON.stringify({ id: 'meeting-1', title: '周会' });
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      withCredentials = false;
      open = vi.fn();
      setRequestHeader = vi.fn();
      send = vi.fn(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 } as ProgressEvent);
        this.upload.onload?.();
        this.onload?.();
      });
      constructor() { FakeXMLHttpRequest.instance = this; }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);

    await createMeetingSummary({
      projectId: 'project-1', title: '周会', meetingDate: '2026-08-05',
      participantUserIds: ['user-1'], file: new File(['全文'], 'meeting.md'),
    }, progress);

    expect(FakeXMLHttpRequest.instance.withCredentials).toBe(true);
    expect(progress).toHaveBeenNthCalledWith(1, {
      phase: 'uploading', percent: 25, loadedBytes: 25, totalBytes: 100,
    });
    expect(progress).toHaveBeenNthCalledWith(2, {
      phase: 'processing', percent: null, loadedBytes: 100, totalBytes: 100,
    });
  });

  it('preserves the server upload error detail', async () => {
    class FakeXMLHttpRequest {
      upload = { onprogress: null, onload: null };
      status = 413;
      responseText = JSON.stringify({ detail: 'meeting content file must not exceed 20 MB' });
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      withCredentials = false;
      open = vi.fn();
      send = vi.fn(() => this.onload?.());
    }
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);

    await expect(createMeetingSummary({
      projectId: 'project-1', title: '周会', meetingDate: '2026-08-05',
      participantUserIds: ['user-1'], file: new File(['全文'], 'meeting.md'),
    }, vi.fn())).rejects.toThrow('meeting content file must not exceed 20 MB');
  });
});
