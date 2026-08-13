import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MeetingNotesPage from './page';

const mocks = vi.hoisted(() => ({
  listProjectCatalog: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listMeetingParticipantOptions: vi.fn(),
  listSummaries: vi.fn(),
  createSummary: vi.fn(),
  getProjectRepository: vi.fn(),
  previewProjectMaterials: vi.fn(),
  confirmMaterialIntake: vi.fn(),
  cancelMaterialIntake: vi.fn(),
  upsertProjectRepository: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  listProjectCatalog: mocks.listProjectCatalog,
  listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
  listMeetingParticipantOptions: mocks.listMeetingParticipantOptions,
  listMeetingSummaries: mocks.listSummaries,
  createMeetingSummary: mocks.createSummary,
  getProjectRepository: mocks.getProjectRepository,
  previewProjectMaterials: mocks.previewProjectMaterials,
  confirmMaterialIntake: mocks.confirmMaterialIntake,
  cancelMaterialIntake: mocks.cancelMaterialIntake,
  upsertProjectRepository: mocks.upsertProjectRepository,
  meetingSummaryFileUrl: (id: string) => `/v4/meeting-summaries/${id}/file`,
}));

describe('MeetingNotesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: true, level: 1 },
    ]);
    mocks.listProjectCatalog.mockResolvedValue([{ id: 'project-1', name: '智慧大脑', department_id: 'research', role: 'owner' }]);
    mocks.listMeetingParticipantOptions.mockResolvedValue([
      { user_id: 'user-1', email: 'zhangsan@local.dev', username: 'zhangsan', nickname: '张三', display_name: '张三' },
      { user_id: 'user-2', email: 'lisi@local.dev', username: 'lisi', nickname: null, display_name: 'lisi' },
      { user_id: 'user-3', email: 'wangwu@local.dev', username: 'wangwu', nickname: '王五', display_name: '王五' },
    ]);
    mocks.listSummaries.mockResolvedValue({ items: [{
      id: 'meeting-1', project_id: 'project-1', project_name: '智慧大脑', title: '产品周会',
      meeting_date: '2026-08-05', participant_user_ids: ['user-1'], participants: ['张三'], tags: ['周会'],
      summary_markdown: '# 产品周会\n\n## 会议摘要\n确认 MCP 访问。', decisions: ['按项目授权'],
      action_items: ['完成检索工具'], source_filename: 'meeting.docx', source_format: 'docx', source_size_bytes: 128,
      created_by: 'u1',
      created_by_name: '张三', created_at: '2026-08-05T01:00:00+00:00',
      updated_at: '2026-08-05T01:00:00+00:00', lexical_score: 0, vector_score: null,
    }] });
    mocks.createSummary.mockResolvedValue({ id: 'meeting-2' });
    mocks.getProjectRepository.mockResolvedValue(null);
  });

  it('shows only project, title, date, team-member checkboxes and a common-format file upload', async () => {
    render(<MeetingNotesPage />);

    expect(screen.getByRole('heading', { name: '上传资料' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '会议记录', selected: true })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '会议记录' })).toBeInTheDocument();
    expect(await screen.findByLabelText('会议标题')).toBeInTheDocument();
    expect(await screen.findByRole('checkbox', { name: /张三/ })).toBeInTheDocument();
    const fileInput = screen.getByLabelText('上传会议内容文件');
    expect(fileInput).toHaveAttribute('accept', expect.stringContaining('.docx'));
    expect(fileInput).toHaveAttribute('accept', expect.stringContaining('.pptx'));
    expect(fileInput).toHaveAttribute('accept', expect.stringContaining('.html'));
    expect(screen.queryByLabelText('会议摘要')).not.toBeInTheDocument();
    expect(screen.queryByText('关键决策')).not.toBeInTheDocument();
    expect(screen.queryByText('行动项')).not.toBeInTheDocument();
    expect(screen.queryByText('标签')).not.toBeInTheDocument();
    expect((await screen.findAllByText('产品周会')).length).toBeGreaterThan(0);
    expect(screen.getByText(/确认 MCP 访问/)).toBeInTheDocument();
  });

  it('shows the complete first-level project hierarchy', async () => {
    render(<MeetingNotesPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('第一分级')).toHaveValue('research');
    });
    expect(mocks.listProjectMemoryDepartments).toHaveBeenCalledWith(true);
    expect(screen.getByLabelText('选择项目')).toHaveValue('project-1');
  });

  it('allows any SmartBrain user to search and select a project they do not belong to', async () => {
    mocks.listProjectCatalog.mockResolvedValue([
      { id: 'project-1', name: '智慧大脑', department_id: 'research', role: null },
      { id: 'project-2', name: '化工研发平台', department_id: 'research', role: null },
    ]);
    mocks.listSummaries.mockResolvedValue({ items: [] });

    render(<MeetingNotesPage />);

    expect(await screen.findByRole('button', { name: '上传会议记录' })).toBeInTheDocument();
    expect(screen.getByText(/所有已启用的智慧大脑用户都可以搜索任意项目并上传/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('搜索项目'), { target: { value: '化' } });
    expect(await screen.findByRole('button', { name: /化工研发平台/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^智慧大脑/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /化工研发平台/ }));
    expect(screen.getByLabelText('选择项目')).toHaveValue('project-2');
    expect(mocks.listSummaries).not.toHaveBeenCalled();
  });

  it('filters all active team members by any single character and keeps checkbox selection', async () => {
    render(<MeetingNotesPage />);

    await screen.findByRole('checkbox', { name: /张三/ });
    fireEvent.change(screen.getByLabelText('搜索参会人'), { target: { value: '王' } });
    expect(screen.getByRole('checkbox', { name: /王五/ })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /张三/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /王五/ }));
    expect(screen.getByText('已选择 1 人')).toBeInTheDocument();
  });

  it('submits selected project members and the meeting content file', async () => {
    render(<MeetingNotesPage />);
    await screen.findAllByText('产品周会');
    fireEvent.change(screen.getByLabelText('会议标题'), { target: { value: '新周会' } });
    fireEvent.change(screen.getByLabelText('会议日期'), { target: { value: '2026-08-05' } });
    fireEvent.click(await screen.findByRole('checkbox', { name: /张三/ }));
    const file = new File(['会议全文'], 'meeting.md', { type: 'text/markdown' });
    fireEvent.change(screen.getByLabelText('上传会议内容文件'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: '上传会议记录' }));

    await waitFor(() => expect(mocks.createSummary).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'project-1', title: '新周会', participantUserIds: ['user-1'], file,
    })));
  });
});
