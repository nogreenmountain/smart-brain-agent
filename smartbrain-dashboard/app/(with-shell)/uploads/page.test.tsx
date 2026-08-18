import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import UploadsWorkspace from '@/components/UploadsWorkspace';

const mocks = vi.hoisted(() => ({
  createMeetingSummary: vi.fn(),
  getProjectRepository: vi.fn(),
  listMeetingParticipantOptions: vi.fn(),
  listMeetingSummaries: vi.fn(),
  listProjectCatalog: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  uploadProjectMaterialsDirect: vi.fn(),
  upsertProjectRepository: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createMeetingSummary: mocks.createMeetingSummary,
    getProjectRepository: mocks.getProjectRepository,
    listMeetingParticipantOptions: mocks.listMeetingParticipantOptions,
    listMeetingSummaries: mocks.listMeetingSummaries,
    listProjectCatalog: mocks.listProjectCatalog,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    uploadProjectMaterialsDirect: mocks.uploadProjectMaterialsDirect,
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
    mocks.uploadProjectMaterialsDirect.mockResolvedValue({
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
    expect(screen.queryByText('搜索会议内容')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '刷新会议记录' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'GitHub 仓库' }));
    expect(await screen.findByLabelText('GitHub 仓库地址')).toHaveValue('https://github.com/example/brain.git');
    expect(screen.getAllByLabelText('选择项目')).toHaveLength(1);
  });

  it('uploads selected project materials directly without an AI sensitive-information step', async () => {
    const user = userEvent.setup();
    render(<UploadsWorkspace />);
    await screen.findByLabelText('项目原始资料');

    const files = [
      new File(['sheet'], 'plan.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
      new File(['word'], 'brief.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }),
      new File(['slides'], 'deck.pptx', { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }),
      new File(['pdf'], 'spec.pdf', { type: 'application/pdf' }),
      new File(['markdown'], 'README.md', { type: 'text/markdown' }),
    ];
    await user.upload(screen.getByLabelText('项目原始资料'), files);
    await user.click(screen.getByRole('button', { name: '上传并提交审批' }));

    await waitFor(() => expect(mocks.uploadProjectMaterialsDirect).toHaveBeenCalledWith(
      'project-1', 'research-direct', files, expect.any(String), expect.any(Function),
    ));
    expect(screen.queryByText(/敏感信息/)).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '文件安全检查' })).not.toBeInTheDocument();
    expect(await screen.findByText('已提交 1 份原始资料，等待管理员审批后入库')).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: '提交仓库审批' }));

    await waitFor(() => expect(mocks.upsertProjectRepository).toHaveBeenCalledWith('project-1', {
      git_url: 'https://github.com/example/updated.git', git_branch: 'develop',
    }));
    expect(await screen.findByText('仓库地址已提交审批，管理员批准后生效')).toBeInTheDocument();
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

  it('shows real material upload progress and a retry-safe error dialog', async () => {
    const user = userEvent.setup();
    let rejectUpload!: (reason: Error) => void;
    mocks.uploadProjectMaterialsDirect.mockImplementation((_projectId, _departmentId, _files, _clientUploadId, onProgress) => {
      onProgress?.({ phase: 'uploading', percent: 42, loadedBytes: 420, totalBytes: 1000 });
      return new Promise((_resolve, reject) => { rejectUpload = reject; });
    });

    render(<UploadsWorkspace />);
    await screen.findByLabelText('项目原始资料');
    const file = new File(['material'], 'design.md', { type: 'text/markdown' });
    await user.upload(screen.getByLabelText('项目原始资料'), file);
    await user.click(screen.getByRole('button', { name: '上传并提交审批' }));

    const progressDialog = await screen.findByRole('dialog', { name: '项目原始资料上传中' });
    expect(progressDialog).toHaveTextContent('正在上传文件');
    expect(screen.getByRole('progressbar', { name: '项目原始资料上传进度' })).toHaveAttribute('aria-valuenow', '42');

    rejectUpload(new Error('网络连接失败'));
    const errorDialog = await screen.findByRole('alertdialog', { name: '项目原始资料上传失败' });
    expect(errorDialog).toHaveTextContent('网络连接失败');
    expect((screen.getByLabelText('项目原始资料') as HTMLInputElement).files).toHaveLength(1);
    const firstClientUploadId = mocks.uploadProjectMaterialsDirect.mock.calls[0][3];
    await user.click(screen.getByRole('button', { name: '关闭错误信息' }));
    expect(screen.queryByRole('alertdialog', { name: '项目原始资料上传失败' })).not.toBeInTheDocument();

    mocks.uploadProjectMaterialsDirect.mockResolvedValueOnce({
      intake_id: 'intake-1', status: 'pending_review', raw_document_count: 1, draft_id: 'draft-1',
    });
    await user.click(screen.getByRole('button', { name: '上传并提交审批' }));
    await waitFor(() => expect(mocks.uploadProjectMaterialsDirect).toHaveBeenCalledTimes(2));
    expect(mocks.uploadProjectMaterialsDirect.mock.calls[1][3]).toBe(firstClientUploadId);
  });

  it('shows and enforces the 500 MB original-material upload limit before sending', async () => {
    const user = userEvent.setup();
    render(<UploadsWorkspace />);
    const input = await screen.findByLabelText('项目原始资料');

    expect(screen.getByText(/单个文件和单批总大小均不超过 500 MB/)).toBeInTheDocument();

    const oversized = new File(['pptx'], 'oversized.pptx', {
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    });
    Object.defineProperty(oversized, 'size', { value: 500 * 1024 * 1024 + 1 });
    await user.upload(input, oversized);
    await user.click(screen.getByRole('button', { name: '上传并提交审批' }));

    expect(await screen.findByRole('alertdialog', { name: '项目原始资料上传失败' })).toHaveTextContent(
      '单个文件不能超过 500 MB',
    );
    expect(mocks.uploadProjectMaterialsDirect).not.toHaveBeenCalled();
  });

  it('shows meeting upload progress, server processing state, and an error dialog', async () => {
    const user = userEvent.setup();
    let rejectMeeting!: (reason: Error) => void;
    mocks.createMeetingSummary.mockImplementation((_input, onProgress) => {
      onProgress?.({ phase: 'uploading', percent: 67, loadedBytes: 670, totalBytes: 1000 });
      onProgress?.({ phase: 'processing', percent: null, loadedBytes: 1000, totalBytes: 1000 });
      return new Promise((_resolve, reject) => { rejectMeeting = reject; });
    });

    render(<UploadsWorkspace initialTab="meetings" />);
    await screen.findByLabelText('会议标题');
    await user.type(screen.getByLabelText('会议标题'), '产品周会');
    fireEvent.change(screen.getByLabelText('会议日期'), { target: { value: '2026-08-13' } });
    await user.click(screen.getByLabelText('参会人 张三，账号 zhangsan'));
    const file = new File(['meeting'], 'meeting.md', { type: 'text/markdown' });
    await user.upload(screen.getByLabelText('上传会议内容文件'), file);
    await user.click(screen.getByRole('button', { name: '上传会议记录' }));

    const progressDialog = await screen.findByRole('dialog', { name: '会议记录上传中' });
    expect(progressDialog).toHaveTextContent('文件已传输完成，服务器正在解析并写入数据库');
    expect(screen.getByRole('progressbar', { name: '会议记录上传进度' })).not.toHaveAttribute('aria-valuenow');

    rejectMeeting(new Error('数据库写入超时'));
    const errorDialog = await screen.findByRole('alertdialog', { name: '会议记录上传失败' });
    expect(errorDialog).toHaveTextContent('数据库写入超时');
    expect((screen.getByLabelText('上传会议内容文件') as HTMLInputElement).files).toHaveLength(1);
  });
});
