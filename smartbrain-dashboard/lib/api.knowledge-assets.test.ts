import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  deleteKnowledgeAsset,
  moveKnowledgeAsset,
  previewKnowledgeAsset,
  renameKnowledgeAsset,
} from './api';

describe('knowledge asset API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses one encoded asset path for preview rename move and delete', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        asset_id: 'asset/1', asset_type: 'meeting_record', project_id: 'project-1',
        name: '周会', format: 'md', content: '# 周会',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })));
    vi.stubGlobal('fetch', fetchMock);

    await previewKnowledgeAsset('meeting_record', 'asset/1');
    await renameKnowledgeAsset('meeting_record', 'asset/1', '新周会');
    await moveKnowledgeAsset('meeting_record', 'asset/1', 'project-2');
    await deleteKnowledgeAsset('meeting_record', 'asset/1');

    expect(fetchMock.mock.calls[0][0]).toContain('/v4/knowledge/assets/meeting_record/asset%2F1/preview');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PATCH' });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ name: '新周会' });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ target_project_id: 'project-2' });
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'DELETE' });
  });
});
