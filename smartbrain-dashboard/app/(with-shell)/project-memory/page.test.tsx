import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProjectMemoryPage from './page';

const mocks = vi.hoisted(() => ({
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  getMe: vi.fn(),
  getProjectRepository: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectMemoryDrafts: vi.fn(),
  listProjects: vi.fn(),
  push: vi.fn(),
  reviewProjectMemoryDraft: vi.fn(),
  previewProjectMaterials: vi.fn(),
  confirmMaterialIntake: vi.fn(),
  cancelMaterialIntake: vi.fn(),
  updateProject: vi.fn(),
  uploadProjectMaterialsBatch: vi.fn(),
  upsertProjectRepository: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mocks.push,
  }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createProject: mocks.createProject,
    deleteProject: mocks.deleteProject,
    getMe: mocks.getMe,
    getProjectRepository: mocks.getProjectRepository,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjectMemoryDrafts: mocks.listProjectMemoryDrafts,
    listProjects: mocks.listProjects,
    reviewProjectMemoryDraft: mocks.reviewProjectMemoryDraft,
    previewProjectMaterials: mocks.previewProjectMaterials,
    confirmMaterialIntake: mocks.confirmMaterialIntake,
    cancelMaterialIntake: mocks.cancelMaterialIntake,
    updateProject: mocks.updateProject,
    uploadProjectMaterialsBatch: mocks.uploadProjectMaterialsBatch,
    upsertProjectRepository: mocks.upsertProjectRepository,
  };
});

const draft = {
  id: 'draft-1',
  project_id: 'project-1',
  department_id: 'research',
  department_name: '研发',
  title: '智慧大脑 长期记忆',
  status: 'pending_review',
  markdown_content: '# 项目长期记忆：智慧大脑\n\n## 1. 项目概览\n内容',
  source_count: 2,
  document_id: null,
  created_at: '2026-07-27T01:00:00Z',
  updated_at: '2026-07-27T01:00:00Z',
};

describe('ProjectMemoryPage', () => {
  beforeEach(() => {
    mocks.createProject.mockReset();
    mocks.deleteProject.mockReset();
    mocks.getMe.mockReset();
    mocks.getProjectRepository.mockReset();
    mocks.listProjectMemoryDepartments.mockReset();
    mocks.listProjectMemoryDrafts.mockReset();
    mocks.listProjects.mockReset();
    mocks.push.mockReset();
    mocks.reviewProjectMemoryDraft.mockReset();
    mocks.previewProjectMaterials.mockReset();
    mocks.confirmMaterialIntake.mockReset();
    mocks.cancelMaterialIntake.mockReset();
    mocks.updateProject.mockReset();
    mocks.uploadProjectMaterialsBatch.mockReset();
    mocks.upsertProjectRepository.mockReset();
    mocks.getMe.mockResolvedValue({
      user_id: 'user-1',
      email: 'admin@local.dev',
      full_name: 'Admin',
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'owner' }],
    });
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发', sort_order: 1 },
      { id: 'marketing', name: '市场', sort_order: 2 },
      { id: 'business', name: '业务', sort_order: 3 },
    ]);
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'owner',
        created_at: '2026-07-28T01:00:00Z',
        completed_at: null,
      },
      {
        id: 'project-2',
        org_id: 'org-1',
        name: '市场素材库',
        environment: 'development',
        department_id: 'marketing',
        role: 'owner',
        created_at: '2026-07-28T02:00:00Z',
        completed_at: '2026-12-31',
      },
    ]);
    mocks.getProjectRepository.mockResolvedValue({
      project_id: 'project-1',
      git_url: 'https://github.com/example/smartbrain.git',
      git_branch: 'main',
    });
    mocks.listProjectMemoryDrafts.mockResolvedValue([draft]);
    mocks.reviewProjectMemoryDraft.mockResolvedValue({
      id: 'draft-1',
      status: 'approved',
      document_id: 'doc-1',
      chunk_count: 4,
      wiki_page_count: 1,
    });
    mocks.previewProjectMaterials.mockResolvedValue({
      id: 'intake-1',
      project_id: 'project-1',
      status: 'preview_ready',
      summary: '1 个文件通过安全检查，1 个文件被拦截',
      model: 'MiniMax-M3',
      used_fallback: false,
      items: [
        {
          id: 'file-1',
          filename: 'README.md',
          format: 'md',
          size_bytes: 128,
          content_hash: 'hash-1',
          recommendation: 'keep',
          included: true,
          reason: '包含可复用的项目启动方式',
          issues: [],
        },
        {
          id: 'file-2',
          filename: 'contacts.txt',
          format: 'txt',
          size_bytes: 64,
          content_hash: 'hash-2',
          recommendation: 'sensitive',
          included: false,
          reason: '检测到个人信息',
          issues: ['sensitive', 'personal_information'],
        },
      ],
    });
    mocks.confirmMaterialIntake.mockResolvedValue({
      intake_id: 'intake-1',
      status: 'pending_review',
      raw_document_count: 1,
      draft_id: 'draft-2',
    });
    mocks.cancelMaterialIntake.mockResolvedValue(undefined);
    mocks.updateProject.mockResolvedValue({
      id: 'project-1',
      org_id: 'org-1',
      name: '智慧大脑二期',
      environment: 'development',
      department_id: 'research',
      created_at: '2026-07-28T01:00:00Z',
      completed_at: '2026-12-31',
    });
    mocks.deleteProject.mockResolvedValue(undefined);
    mocks.uploadProjectMaterialsBatch.mockResolvedValue({
      raw_document_count: 1,
      raw_documents: [
        {
          document_id: 'doc-2',
          filename: 'readme.md',
          format: 'md',
          chunk_count: 1,
          status: 'ready',
        },
      ],
      draft: {
        ...draft,
        id: 'draft-2',
        source_count: 1,
      },
    });
  });

  it('runs the department, repository and one-step memory approval flow', async () => {
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    expect(await screen.findByRole('heading', { name: '项目管理' })).toBeInTheDocument();
    expect(screen.getAllByText('智慧大脑').length).toBeGreaterThan(0);
    expect(screen.queryByText('市场素材库')).not.toBeInTheDocument();
    expect(screen.queryByText('项目成员')).not.toBeInTheDocument();

    await screen.findByDisplayValue('https://github.com/example/smartbrain.git');
    await user.clear(screen.getByLabelText('GitHub 仓库地址'));
    await user.type(screen.getByLabelText('GitHub 仓库地址'), 'https://github.com/example/new.git');
    await user.click(screen.getByRole('button', { name: '保存仓库' }));
    await waitFor(() => {
      expect(mocks.upsertProjectRepository).toHaveBeenCalledWith('project-1', {
        git_url: 'https://github.com/example/new.git',
        git_branch: 'main',
      });
    });

    expect(screen.queryByLabelText('项目记忆资料')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成长期记忆草稿' })).not.toBeInTheDocument();
    expect(await screen.findByText(/# 项目长期记忆：智慧大脑/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('备注（可选）'), {
      target: { value: '格式统一，可以入库' },
    });
    await user.click(screen.getByRole('button', { name: '批准并入库' }));
    await waitFor(() => {
      expect(mocks.reviewProjectMemoryDraft).toHaveBeenCalledWith(
        'draft-1',
        'approve',
        '格式统一，可以入库',
      );
    });
  });

  it('updates project metadata, opens knowledge base and deletes the selected project', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    expect(await screen.findByRole('heading', { name: '项目管理' })).toBeInTheDocument();
    await screen.findByDisplayValue('智慧大脑');
    fireEvent.change(screen.getByLabelText('当前项目名称'), {
      target: { value: '智慧大脑二期' },
    });
    fireEvent.change(screen.getByLabelText('当前项目结项日期'), {
      target: { value: '2026-12-31' },
    });
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mocks.updateProject).toHaveBeenCalledWith('project-1', {
        name: '智慧大脑二期',
        completed_at: '2026-12-31',
      });
    });

    await user.click(screen.getByRole('button', { name: '访问对应项目知识库' }));
    expect(mocks.push).toHaveBeenCalledWith('/knowledge?project_id=project-1');

    await user.click(screen.getByRole('button', { name: '删除项目' }));
    await waitFor(() => {
      expect(mocks.deleteProject).toHaveBeenCalledWith('project-1');
    });
  });

  it('creates a project without asking the admin to choose an organization', async () => {
    mocks.createProject.mockResolvedValue({
      id: 'project-3',
      org_id: 'org-1',
      name: '新研发项目',
      environment: 'development',
      department_id: 'research',
      created_at: '2026-07-28T03:00:00Z',
      completed_at: null,
    });
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    expect(await screen.findByRole('heading', { name: '项目管理' })).toBeInTheDocument();
    expect(screen.queryByText('所属组织')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('新项目名称'), '新研发项目');
    await user.click(screen.getByRole('button', { name: '创建项目' }));

    await waitFor(() => {
      expect(mocks.createProject).toHaveBeenCalledWith({
        org_id: 'org-1',
        name: '新研发项目',
        environment: 'development',
        department_id: 'research',
        completed_at: null,
      });
    });
  });

  it('shows only project list, profile, repository and material upload for regular project members', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mocks.getMe.mockResolvedValue({
      user_id: 'user-2',
      email: 'member@local.dev',
      full_name: 'Member',
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'business_user' }],
    });
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'developer',
        created_at: '2026-07-28T01:00:00Z',
        completed_at: null,
      },
    ]);
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    expect(await screen.findByRole('heading', { name: '项目管理' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '项目列表' })).toBeInTheDocument();
    expect(screen.getByText('PROJECT PROFILE')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'GitHub 仓库' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '上传项目资料' })).toBeInTheDocument();

    expect(screen.queryByRole('heading', { name: '创建项目' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('当前项目名称')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('当前项目结项日期')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '删除项目' })).not.toBeInTheDocument();
    expect(screen.queryByText('待确认记忆')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批准并入库' })).not.toBeInTheDocument();

    const repoInput = await screen.findByDisplayValue('https://github.com/example/smartbrain.git');
    await user.clear(repoInput);
    await user.type(screen.getByLabelText('GitHub 仓库地址'), 'https://github.com/example/member.git');
    await user.click(screen.getByRole('button', { name: '保存仓库' }));
    await waitFor(() => {
      expect(mocks.upsertProjectRepository).toHaveBeenCalledWith('project-1', {
        git_url: 'https://github.com/example/member.git',
        git_branch: 'main',
      });
    });

    const files = [new File(['项目资料'], 'readme.md', { type: 'text/markdown' })];
    await user.upload(screen.getByLabelText('项目原始资料'), files);
    await user.click(screen.getByRole('button', { name: '上传资料' }));
    await waitFor(() => {
      expect(mocks.previewProjectMaterials).toHaveBeenCalledWith('project-1', 'research', files);
    });
    expect(await screen.findByRole('dialog', { name: '文件安全检查' })).toBeInTheDocument();
    expect(screen.getByText('检测到个人信息')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '上传通过检测的文件' }));
    await waitFor(() => {
      expect(mocks.confirmMaterialIntake).toHaveBeenCalledWith('intake-1', ['file-1']);
    });
  });

  it('lets a member cancel the entire staged upload from the security dialog', async () => {
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    await screen.findByRole('heading', { name: '项目管理' });
    const files = [new File(['项目资料'], 'readme.md', { type: 'text/markdown' })];
    await user.upload(screen.getByLabelText('项目原始资料'), files);
    await user.click(screen.getByRole('button', { name: '上传资料' }));
    await screen.findByRole('dialog', { name: '文件安全检查' });
    await user.click(screen.getByRole('button', { name: '全部不上传' }));

    await waitFor(() => expect(mocks.cancelMaterialIntake).toHaveBeenCalledWith('intake-1'));
    expect(mocks.confirmMaterialIntake).not.toHaveBeenCalled();
  });
});
