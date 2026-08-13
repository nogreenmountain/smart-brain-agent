import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import UploadsWorkspace from '@/components/UploadsWorkspace';

const mocks = vi.hoisted(() => ({
  cancelMaterialIntake: vi.fn(),
  confirmMaterialIntake: vi.fn(),
  createMeetingSummary: vi.fn(),
  getProjectRepository: vi.fn(),
  listMeetingParticipantOptions: vi.fn(),
  listMeetingSummaries: vi.fn(),
  listProjectCatalog: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  previewProjectMaterials: vi.fn(),
  upsertProjectRepository: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    cancelMaterialIntake: mocks.cancelMaterialIntake,
    confirmMaterialIntake: mocks.confirmMaterialIntake,
    createMeetingSummary: mocks.createMeetingSummary,
    getProjectRepository: mocks.getProjectRepository,
    listMeetingParticipantOptions: mocks.listMeetingParticipantOptions,
    listMeetingSummaries: mocks.listMeetingSummaries,
    listProjectCatalog: mocks.listProjectCatalog,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    previewProjectMaterials: mocks.previewProjectMaterials,
    upsertProjectRepository: mocks.upsertProjectRepository,
    meetingSummaryFileUrl: (id: string) => `/v4/meeting-summaries/${id}/file`,
  };
});

describe('UploadsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: false, level: 1 },
      { id: 'research-direct', name: '直属项目', sort_order: 0, parent_id: 'research', parent_name: '研发支撑', allows_projects: true, level: 2 },
    ]);
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1', org_id: 'org-1', name: '智慧大脑', environment: 'development',
        department_id: 'research-direct', role: 'owner',
      },
    ]);
    mocks.listMeetingParticipantOptions.mockResolvedValue([
      { user_id: 'user-1', email: 'zhangsan@local.dev', username: 'zhangsan', nickname: '张三', display_name: '张三' },
    ]);
    mocks.listMeetingSummaries.mockResolvedValue({ items: [] });
    mocks.getProjectRepository.mockResolvedValue({
      project_id: 'project-1', git_url: 'https://github.com/example/brain.git', git_branch: 'main',
    });
    mocks.previewProjectMaterials.mockResolvedValue({
      id: 'intake-1', project_id: 'project-1', status: 'preview_ready', summary: '2 个文件已完成安全检查',
      model: 'test-model', used_fallback: false,
      items: [
        {
          id: 'file-safe', filename: 'safe.md', format: 'md', size_bytes: 10, content_hash: 'a',
          recommendation: 'keep', included: true, reason: '未发现敏感信息', issues: [],
        },
        {
          id: 'file-secret', filename: 'secret.txt', format: 'txt', size_bytes: 12, content_hash: 'b',
          recommendation: 'sensitive', included: false, reason: '发现凭据', issues: ['credential'],
        },
      ],
    });
    mocks.confirmMaterialIntake.mockResolvedValue({
      intake_id: 'intake-1', status: 'pending_review', raw_document_count: 1, draft_id: 'draft-1',
    });
    mocks.upsertProjectRepository.mockResolvedValue({
      project_id: 'project-1', git_url: 'https://github.com/example/updated.git', git_branch: 'develop',
    });
  });

  it('combines three material tools behind one shared project selector', async () => {
    const user = userEvent.setup();
    render(<UploadsWorkspace />);

    expect(screen.getByRole('heading', { name: '上传资料' })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: '项目原始资料', selected: true })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '会议记录' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'GitHub 仓库' })).toBeInTheDocument();
    expect(screen.getAllByLabelText('选择项目')).toHaveLength(1);
    expect(screen.getByLabelText('项目原始资料')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '会议记录' }));
    expect(await screen.findByLabelText('会议标题')).toBeInTheDocument();
    expect(screen.getAllByLabelText('选择项目')).toHaveLength(1);

    await user.click(screen.getByRole('tab', { name: 'GitHub 仓库' }));
    expect(await screen.findByLabelText('GitHub 仓库地址')).toHaveValue('https://github.com/example/brain.git');
    expect(screen.getAllByLabelText('选择项目')).toHaveLength(1);
  });

  it('keeps raw-material preview, scan, confirm, and cancel behavior', async () => {
    const user = userEvent.setup();
    render(<UploadsWorkspace />);
    await screen.findByLabelText('项目原始资料');

    const files = [
      new File(['safe'], 'safe.md', { type: 'text/markdown' }),
      new File(['secret'], 'secret.txt', { type: 'text/plain' }),
    ];
    await user.upload(screen.getByLabelText('项目原始资料'), files);
    await user.click(screen.getByRole('button', { name: '检查并预览' }));

    await waitFor(() => expect(mocks.previewProjectMaterials).toHaveBeenCalledWith(
      'project-1', 'research-direct', files,
    ));
    expect(await screen.findByRole('dialog', { name: '文件安全检查' })).toBeInTheDocument();
    expect(screen.getByText('safe.md')).toBeInTheDocument();
    expect(screen.getByText('secret.txt')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '上传通过检测的文件' }));
    await waitFor(() => expect(mocks.confirmMaterialIntake).toHaveBeenCalledWith('intake-1', ['file-safe']));

    await user.upload(screen.getByLabelText('项目原始资料'), files);
    await user.click(screen.getByRole('button', { name: '检查并预览' }));
    await screen.findByRole('dialog', { name: '文件安全检查' });
    await user.click(screen.getByRole('button', { name: '全部不上传' }));
    await waitFor(() => expect(mocks.cancelMaterialIntake).toHaveBeenCalledWith('intake-1'));
  });

  it('loads and saves the selected project repository', async () => {
    const user = userEvent.setup();
    render(<UploadsWorkspace />);

    await user.click(await screen.findByRole('tab', { name: 'GitHub 仓库' }));
    await waitFor(() => expect(mocks.getProjectRepository).toHaveBeenCalledWith('project-1'));
    await user.clear(screen.getByLabelText('GitHub 仓库地址'));
    await user.type(screen.getByLabelText('GitHub 仓库地址'), 'https://github.com/example/updated.git');
    await user.clear(screen.getByLabelText('默认分支'));
    await user.type(screen.getByLabelText('默认分支'), 'develop');
    fireEvent.click(screen.getByRole('button', { name: '保存仓库' }));

    await waitFor(() => expect(mocks.upsertProjectRepository).toHaveBeenCalledWith('project-1', {
      git_url: 'https://github.com/example/updated.git', git_branch: 'develop',
    }));
  });

  it('keeps meeting uploads open to all users while protecting materials and repository tools', async () => {
    const user = userEvent.setup();
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-public', org_id: 'org-2', name: '公开会议项目', environment: 'development',
        department_id: 'research-direct', role: undefined,
      },
    ]);

    render(<UploadsWorkspace />);

    expect(await screen.findByLabelText('项目原始资料')).toBeDisabled();
    expect(screen.getByText('原始资料和仓库配置仅对项目成员开放。')).toBeInTheDocument();
    expect(mocks.getProjectRepository).not.toHaveBeenCalled();

    await user.click(screen.getByRole('tab', { name: '会议记录' }));
    expect(await screen.findByRole('button', { name: '上传会议记录' })).toBeEnabled();

    await user.click(screen.getByRole('tab', { name: 'GitHub 仓库' }));
    expect(screen.getByLabelText('GitHub 仓库地址')).toBeDisabled();
    expect(mocks.getProjectRepository).not.toHaveBeenCalled();
  });
});
