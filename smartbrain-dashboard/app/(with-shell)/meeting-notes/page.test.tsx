import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MeetingNotesPage from './page';

const mocks = vi.hoisted(() => ({
  listProjectCatalog: vi.fn(),
  listSummaries: vi.fn(),
  createSummary: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  listProjectCatalog: mocks.listProjectCatalog,
  listMeetingSummaries: mocks.listSummaries,
  createMeetingSummary: mocks.createSummary,
}));

describe('MeetingNotesPage', () => {
  beforeEach(() => {
    mocks.listProjectCatalog.mockResolvedValue([{ id: 'project-1', name: '智慧大脑', role: 'owner' }]);
    mocks.listSummaries.mockResolvedValue({ items: [{
      id: 'meeting-1', project_id: 'project-1', project_name: '智慧大脑', title: '产品周会',
      meeting_date: '2026-08-05', participants: ['张三'], tags: ['周会'],
      summary_markdown: '# 产品周会\n\n## 会议摘要\n确认 MCP 访问。', decisions: ['按项目授权'],
      action_items: ['完成检索工具'], source_filename: 'meeting.md', created_by: 'u1',
      created_by_name: '张三', created_at: '2026-08-05T01:00:00+00:00',
      updated_at: '2026-08-05T01:00:00+00:00', lexical_score: 0, vector_score: null,
    }] });
    mocks.createSummary.mockResolvedValue({ id: 'meeting-2' });
  });

  it('shows a standalone upload form and historical summaries', async () => {
    render(<MeetingNotesPage />);

    expect(screen.getByRole('heading', { name: '会议记录' })).toBeInTheDocument();
    expect(await screen.findByLabelText('会议标题')).toBeInTheDocument();
    expect(screen.getByLabelText('上传 Markdown 或 TXT')).toBeInTheDocument();
    expect((await screen.findAllByText('产品周会')).length).toBeGreaterThan(0);
    expect(screen.getByText(/确认 MCP 访问/)).toBeInTheDocument();
  });

  it('submits pasted summary content', async () => {
    render(<MeetingNotesPage />);
    await screen.findAllByText('产品周会');
    fireEvent.change(screen.getByLabelText('会议标题'), { target: { value: '新周会' } });
    fireEvent.change(screen.getByLabelText('会议日期'), { target: { value: '2026-08-05' } });
    fireEvent.change(screen.getByLabelText('会议摘要'), { target: { value: '新的摘要' } });
    fireEvent.click(screen.getByRole('button', { name: '上传会议摘要' }));

    await waitFor(() => expect(mocks.createSummary).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'project-1', title: '新周会', summary: '新的摘要',
    })));
  });
});
