import { afterEach, describe, expect, it, vi } from 'vitest';

import { uploadProjectMaterialsDirect } from './api';

describe('direct project material upload API', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('resumes from server-reported bytes, uploads binary chunks with cookies, and completes once', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        intake_id: 'intake-1',
        status: 'uploading',
        files: [{
          id: 'file-1', filename: 'README.md', format: 'md', size_bytes: 5, received_bytes: 2,
        }],
      }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        intake_id: 'intake-1', status: 'pending_review', raw_document_count: 1, draft_id: 'draft-1',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const requests: Array<{
      method: string;
      url: string;
      withCredentials: boolean;
      headers: Record<string, string>;
      body: Blob;
    }> = [];
    class FakeXMLHttpRequest {
      method = '';
      url = '';
      withCredentials = false;
      status = 0;
      responseText = '';
      headers: Record<string, string> = {};
      upload: { onprogress: ((event: ProgressEvent) => void) | null; onload: (() => void) | null } = {
        onprogress: null,
        onload: null,
      };
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      onload: (() => void) | null = null;

      open(method: string, url: string) {
        this.method = method;
        this.url = url;
      }

      setRequestHeader(name: string, value: string) {
        this.headers[name] = value;
      }

      send(body: Blob) {
        requests.push({
          method: this.method,
          url: this.url,
          withCredentials: this.withCredentials,
          headers: this.headers,
          body,
        });
        this.upload.onprogress?.({ loaded: body.size, total: body.size, lengthComputable: true } as ProgressEvent);
        this.upload.onload?.();
        this.status = 200;
        this.responseText = JSON.stringify({ file_id: 'file-1', received_bytes: 5, size_bytes: 5 });
        this.onload?.();
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);

    const progress = vi.fn();
    const result = await uploadProjectMaterialsDirect(
      'project-1',
      'research-direct',
      [new File(['hello'], 'README.md', { type: 'text/markdown' })],
      '00000000-0000-4000-8000-000000000001',
      progress,
    );

    expect(result.status).toBe('pending_review');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      project_id: 'project-1',
      department_id: 'research-direct',
      client_upload_id: '00000000-0000-4000-8000-000000000001',
      files: [{ filename: 'README.md', size_bytes: 5 }],
    });
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      method: 'PUT',
      url: 'http://localhost:8000/v4/knowledge/material-intakes/upload-sessions/intake-1/files/file-1?offset=2',
      withCredentials: true,
      headers: { 'Content-Type': 'application/octet-stream' },
    });
    expect(requests[0].body.size).toBe(3);
    expect(fetchMock.mock.calls[1][0]).toBe(
      'http://localhost:8000/v4/knowledge/material-intakes/upload-sessions/intake-1/complete',
    );
    expect(progress).toHaveBeenCalledWith({
      phase: 'uploading', percent: 40, loadedBytes: 2, totalBytes: 5,
    });
    expect(progress).toHaveBeenLastCalledWith({
      phase: 'processing', percent: null, loadedBytes: 5, totalBytes: 5,
    });
  });
});
