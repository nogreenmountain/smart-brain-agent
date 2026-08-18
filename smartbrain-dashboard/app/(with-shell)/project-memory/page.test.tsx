import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProjectMemoryPage from './page';

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));

const mocks = vi.hoisted(() => ({
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  getMe: vi.fn(),
  getProjectRepository: vi.fn(),
  listProjectCatalog: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectMemoryDrafts: vi.fn(),
  listProjectMemoryReviewQueue: vi.fn(),
  listProjects: vi.fn(),
  reviewProjectMemoryDraft: vi.fn(),
  updateProject: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => navigation,
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createProject: mocks.createProject,
    deleteProject: mocks.deleteProject,
    getMe: mocks.getMe,
    getProjectRepository: mocks.getProjectRepository,
    listProjectCatalog: mocks.listProjectCatalog,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjectMemoryDrafts: mocks.listProjectMemoryDrafts,
    listProjectMemoryReviewQueue: mocks.listProjectMemoryReviewQueue,
    listProjects: mocks.listProjects,
    reviewProjectMemoryDraft: mocks.reviewProjectMemoryDraft,
    updateProject: mocks.updateProject,
  };
});

const departments = [
  { id: 'research', name: '研发支撑', sort_order: 10, parent_id: null, allows_projects: false, level: 1 },
  {
    id: 'research-direct',
    name: '直属分级',
    sort_order: 11,
    parent_id: 'research',
    parent_name: '研发支撑',
    allows_projects: true,
    level: 2,
    is_direct: true,
  },
  { id: 'industry', name: '产业侧', sort_order: 20, parent_id: null, allows_projects: false, level: 1 },
  {
    id: 'industry-direct',
    name: '直属分级',
    sort_order: 21,
    parent_id: 'industry',
    parent_name: '产业侧',
    allows_projects: true,
    level: 2,
    is_direct: true,
  },
  {
    id: 'marketing',
    name: '市场',
    sort_order: 22,
    parent_id: 'industry',
    parent_name: '产业侧',
    allows_projects: true,
    level: 2,
  },
];

const project = {
  id: 'project-1',
  org_id: 'org-1',
  name: '智慧大脑',
  environment: 'development',
  department_id: 'research-direct',
  role: 'owner' as const,
  created_at: '2026-07-28T01:00:00Z',
  completed_at: null,
};

const draft = {
  id: 'draft-1',
  project_id: 'project-1',
  department_id: 'research-direct',
  department_name: '直属分级',
  title: '智慧大脑 长期记忆',
  status: 'pending_review' as const,
  markdown_content: '# 项目长期记忆：智慧大脑\n\n## 1. 项目概览\n内容',
  source_count: 2,
  document_id: null,
  created_at: '2026-07-27T01:00:00Z',
  updated_at: '2026-07-27T01:00:00Z',
};

describe('ProjectMemoryPage compatibility route', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getMe.mockResolvedValue({
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      full_name: 'hanshangbo',
      is_system_admin: true,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'owner' }],
    });
    mocks.listProjectMemoryDepartments.mockResolvedValue(departments);
    mocks.listProjectCatalog.mockResolvedValue([project]);
    mocks.listProjects.mockResolvedValue([project]);
    mocks.listProjectMemoryDrafts.mockResolvedValue([draft]);
    mocks.listProjectMemoryReviewQueue.mockResolvedValue([
      {
        ...draft,
        project_name: '智慧大脑',
        department_path: '研发支撑 / 直属分级',
        uploader: {
          user_id: 'member-1',
          username: 'member1',
          nickname: '普通成员',
          display_name: '普通成员',
        },
        file_names: ['项目资料.docx'],
        total_size_bytes: 1024,
      },
    ]);
    mocks.getProjectRepository.mockResolvedValue({
      project_id: 'project-1',
      git_url: 'https://github.com/example/smartbrain.git',
      git_branch: 'main',
    });
    mocks.reviewProjectMemoryDraft.mockResolvedValue({
      id: 'draft-1',
      status: 'approved',
      document_id: 'doc-1',
      chunk_count: 4,
      wiki_page_count: 1,
    });
    mocks.updateProject.mockResolvedValue({ ...project, name: '智慧大脑二期', completed_at: '2026-12-31' });
    mocks.deleteProject.mockResolvedValue(undefined);
  });

  it('keeps the legacy address on the administrator workbench and approves pending project material', async () => {
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    expect(await screen.findByRole('heading', { name: '管理工作台' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '项目管理' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('PROJECT PROFILE')).toBeInTheDocument();
    expect((await screen.findAllByText('智慧大脑 长期记忆')).length).toBeGreaterThan(0);
    expect(screen.getByText(/# 项目长期记忆：智慧大脑/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('备注（可选）'), {
      target: { value: '格式统一，可以入库' },
    });
    await user.click(screen.getByRole('button', { name: '批准并入库' }));

    await waitFor(() => expect(mocks.reviewProjectMemoryDraft).toHaveBeenCalledWith(
      'draft-1',
      'approve',
      '格式统一，可以入库',
    ));
  });

  it('keeps profile editing, knowledge-base navigation, and project deletion on the legacy address', async () => {
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    await screen.findByDisplayValue('智慧大脑');
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '智慧大脑二期' } });
    fireEvent.change(screen.getByLabelText('结项日期'), { target: { value: '2026-12-31' } });
    await user.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(mocks.updateProject).toHaveBeenCalledWith('project-1', {
      name: '智慧大脑二期',
      completed_at: '2026-12-31',
    }));

    await user.click(screen.getByRole('button', { name: '知识库' }));
    expect(navigation.push).toHaveBeenCalledWith('/knowledge?project_id=project-1');

    await user.click(screen.getByRole('button', { name: '删除项目' }));
    expect(screen.getByText(/删除会影响项目成员关系/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/请输入项目名称/), '智慧大脑二期');
    await user.click(screen.getByRole('button', { name: '确认永久删除' }));
    await waitFor(() => expect(mocks.deleteProject).toHaveBeenCalledWith('project-1', '智慧大脑二期'));
  });

  it('creates projects through a first-level category and its direct second-level category', async () => {
    mocks.createProject.mockResolvedValue({
      ...project,
      id: 'project-2',
      name: '新研发项目',
      created_at: '2026-07-28T03:00:00Z',
    });
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    await screen.findByRole('heading', { name: '创建项目' });
    expect(screen.getByLabelText('项目第一分级')).toHaveValue('research');
    expect(screen.getByLabelText('项目第二分级')).toHaveValue('research-direct');
    expect(screen.getAllByRole('option', { name: '直属分级' }).length).toBeGreaterThan(0);
    expect(screen.queryByText('所属组织')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('新项目名称'), '新研发项目');
    await user.click(screen.getByRole('button', { name: '创建项目' }));

    await waitFor(() => expect(mocks.createProject).toHaveBeenCalledWith({
      org_id: 'org-1',
      name: '新研发项目',
      environment: 'development',
      department_id: 'research-direct',
      completed_at: null,
    }));
  });

  it('keeps category management for system administrators and protects direct categories', async () => {
    const user = userEvent.setup();
    render(<ProjectMemoryPage />);

    await user.click(await screen.findByRole('button', { name: '打开分类管理' }));
    expect(screen.getByRole('dialog', { name: '分类管理' })).toBeInTheDocument();
    expect(screen.getByText(/第一、第二分级只用于分类/)).toBeInTheDocument();
    expect(screen.getAllByText('系统分级 · 自动维护')).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: '改名' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: '删除分类' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: /拖动排序/ }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('spinbutton', { name: /分类排序/ })).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: '改名' })[0]);
    expect(screen.getByRole('button', { name: '保存分类' })).toBeInTheDocument();
  });

  it('does not render repository or raw-material upload tools after they moved to Uploads', async () => {
    render(<ProjectMemoryPage />);

    await screen.findByText('PROJECT PROFILE');
    expect(screen.queryByRole('heading', { name: 'GitHub 仓库' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '上传项目资料' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('GitHub 仓库地址')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('项目原始资料')).not.toBeInTheDocument();
    expect(mocks.getProjectRepository).not.toHaveBeenCalled();
  });

  it('redirects ordinary members to Profile without loading project-management data', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'member-1',
      email: 'member@local.dev',
      full_name: 'Member',
      is_system_admin: false,
      can_manage_projects: false,
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'business_user' }],
    });

    render(<ProjectMemoryPage />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith('/profile'));
    expect(mocks.listProjectCatalog).not.toHaveBeenCalled();
    expect(mocks.listProjects).not.toHaveBeenCalled();
    expect(mocks.listProjectMemoryDepartments).not.toHaveBeenCalled();
    expect(screen.queryByText('PROJECT PROFILE')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '创建项目' })).not.toBeInTheDocument();
  });
});
