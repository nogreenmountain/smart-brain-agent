import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';
import AdminPage from './page';

vi.mock('@/components/management-workspace/TeamDirectoryPanel', () => ({
  TeamDirectoryPanel: () => <div data-testid="team-directory-panel">团队账号维护</div>,
}));

vi.mock('@/components/management-workspace/ProjectMembersPanel', () => ({
  ProjectMembersPanel: ({ project, canManage }: { project: { id: string; name: string } | null; canManage: boolean }) => (
    <div data-testid="project-members-panel" data-project-id={project?.id || ''} data-can-manage={String(canManage)}>
      {project ? `${project.name} 项目成员` : '请选择项目'}
    </div>
  ),
}));

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));

const mocks = vi.hoisted(() => ({
  createProjectMemoryDepartment: vi.fn(),
  getMe: vi.fn(),
  getProjectRepository: vi.fn(),
  listProjectCreationRequests: vi.fn(),
  listProjectCatalog: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectMemoryDrafts: vi.fn(),
  listProjectMemoryReviewQueue: vi.fn(),
  listProjects: vi.fn(),
  reorderProjectMemoryDepartments: vi.fn(),
  reviewProjectCreationRequest: vi.fn(),
  reviewProjectMemoryDraft: vi.fn(),
  submitProjectCreationRequest: vi.fn(),
  updateProject: vi.fn(),
  startProjectDepartmentMigration: vi.fn(),
  getProjectDepartmentMigration: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => navigation,
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createProjectMemoryDepartment: mocks.createProjectMemoryDepartment,
    getMe: mocks.getMe,
    getProjectRepository: mocks.getProjectRepository,
    listProjectCreationRequests: mocks.listProjectCreationRequests,
    listProjectCatalog: mocks.listProjectCatalog,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjectMemoryDrafts: mocks.listProjectMemoryDrafts,
    listProjectMemoryReviewQueue: mocks.listProjectMemoryReviewQueue,
    listProjects: mocks.listProjects,
    reorderProjectMemoryDepartments: mocks.reorderProjectMemoryDepartments,
    reviewProjectCreationRequest: mocks.reviewProjectCreationRequest,
    reviewProjectMemoryDraft: mocks.reviewProjectMemoryDraft,
    submitProjectCreationRequest: mocks.submitProjectCreationRequest,
    updateProject: mocks.updateProject,
    startProjectDepartmentMigration: mocks.startProjectDepartmentMigration,
    getProjectDepartmentMigration: mocks.getProjectDepartmentMigration,
  };
});

describe('AdminPage', () => {
  let departments: {
    id: string;
    name: string;
    sort_order: number;
    parent_id?: string | null;
    parent_name?: string | null;
    allows_projects?: boolean;
    level?: number;
    is_direct?: boolean;
  }[];

  beforeEach(() => {
    window.history.replaceState({}, '', '/admin');
    departments = [
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
    ];
    Object.values(mocks).forEach((mock) => mock.mockReset());
    navigation.push.mockReset();
    navigation.replace.mockReset();
    mocks.getMe.mockResolvedValue({
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      full_name: 'hanshangbo',
      is_system_admin: true,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'owner' }],
    });
    mocks.listProjectMemoryDepartments.mockImplementation(async () => departments);
    const defaultProjects = [
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑agent',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
      },
    ];
    mocks.listProjectCatalog.mockResolvedValue(defaultProjects);
    mocks.listProjects.mockResolvedValue(defaultProjects);
    mocks.getProjectRepository.mockResolvedValue(null);
    mocks.listProjectCreationRequests.mockResolvedValue([]);
    mocks.listProjectMemoryDrafts.mockResolvedValue([
      {
        id: 'approved-1',
        project_id: 'project-1',
        department_id: 'research-direct',
        department_name: '直属分级',
        title: '已审批资料不应显示',
        status: 'approved',
        markdown_content: 'approved',
        source_count: 1,
        document_id: 'doc-1',
        created_at: '2026-08-10T00:00:00Z',
        updated_at: '2026-08-10T00:00:00Z',
      },
      {
        id: 'pending-1',
        project_id: 'project-1',
        department_id: 'research-direct',
        department_name: '直属分级',
        title: '待审批资料一',
        status: 'pending_review',
        markdown_content: 'long approval content one',
        source_count: 1,
        document_id: null,
        created_at: '2026-08-10T01:00:00Z',
        updated_at: '2026-08-10T01:00:00Z',
      },
      {
        id: 'pending-2',
        project_id: 'project-1',
        department_id: 'research-direct',
        department_name: '直属分级',
        title: '待审批资料二',
        status: 'pending_review',
        markdown_content: 'long approval content two',
        source_count: 1,
        document_id: null,
        created_at: '2026-08-10T02:00:00Z',
        updated_at: '2026-08-10T02:00:00Z',
      },
    ]);
    mocks.listProjectMemoryReviewQueue.mockResolvedValue([
      {
        id: 'pending-1', project_id: 'project-1', project_name: '智慧大脑agent',
        department_id: 'research-direct', department_name: '直属分级', department_path: '研发支撑 / 直属分级',
        title: '待审批资料一', status: 'pending_review', markdown_content: 'long approval content one', source_count: 1,
        uploader: { user_id: 'member-1', username: 'member1', nickname: '普通成员', display_name: '普通成员' },
        file_names: ['需求.docx'], total_size_bytes: 1024,
        created_at: '2026-08-10T01:00:00Z', updated_at: '2026-08-10T01:00:00Z',
      },
      {
        id: 'pending-other', project_id: 'project-2', project_name: '跨项目审批示例',
        department_id: 'industry-direct', department_name: '直属分级', department_path: '产业侧 / 直属分级',
        title: '另一个项目的审批资料', status: 'pending_review', markdown_content: 'other project approval', source_count: 2,
        uploader: { user_id: 'member-2', username: 'member2', nickname: null, display_name: 'member2' },
        file_names: ['方案.pptx', '预算.xlsx'], total_size_bytes: 4096,
        created_at: '2026-08-10T02:00:00Z', updated_at: '2026-08-10T02:00:00Z',
      },
    ]);
    mocks.reviewProjectMemoryDraft.mockResolvedValue({
      id: 'pending-1',
      status: 'approved',
      document_id: 'doc-new',
      chunk_count: 3,
      wiki_page_count: 1,
    });
    mocks.startProjectDepartmentMigration.mockResolvedValue({
      id: 'migration-1',
      project_id: 'project-1',
      source_department_id: 'research-direct',
      target_department_id: 'business',
      status: 'completed',
      progress: 100,
      current_step: 'completed',
      raw_material_count: 2,
      wiki_page_count: 3,
      meeting_record_count: 1,
      verified: true,
    });
    mocks.getProjectDepartmentMigration.mockResolvedValue({
      id: 'migration-1',
      project_id: 'project-1',
      source_department_id: 'research-direct',
      target_department_id: 'business',
      status: 'completed',
      progress: 100,
      current_step: 'completed',
      raw_material_count: 2,
      wiki_page_count: 3,
      meeting_record_count: 1,
      verified: true,
    });
    mocks.createProjectMemoryDepartment.mockImplementation(async (input) => {
      const created = { id: 'dept-auto-generated', ...input, sort_order: departments.length + 1 };
      departments = [...departments, created];
      return created;
    });
  });

  it('uses an AI-workspace-style top navigation and keeps the selected management view in the URL', async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    expect(await screen.findByRole('heading', { name: '管理工作台' })).toBeInTheDocument();
    const projectsTab = screen.getByRole('tab', { name: '项目管理' });
    const membersTab = screen.getByRole('tab', { name: '成员管理' });
    expect(projectsTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('PROJECT PROFILE')).toBeInTheDocument();
    expect(screen.getByTestId('project-members-panel')).toHaveAttribute('data-project-id', 'project-1');
    expect(screen.getByTestId('project-members-panel')).toHaveAttribute('data-can-manage', 'true');

    await user.click(membersTab);

    expect(await screen.findByTestId('team-directory-panel')).toBeInTheDocument();
    expect(membersTab).toHaveAttribute('aria-selected', 'true');
    expect(window.location.pathname + window.location.search).toBe('/admin?view=members');
    expect(screen.queryByText('PROJECT PROFILE')).not.toBeInTheDocument();
    expect(screen.queryByTestId('project-members-panel')).not.toBeInTheDocument();
    expect(screen.queryByText('项目筛选')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByText('移出项目')).not.toBeInTheDocument();

    window.history.pushState({}, '', '/admin');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByText('PROJECT PROFILE')).toBeInTheDocument();
  });

  it('moves the project-member workspace with the selected project', async () => {
    const user = userEvent.setup();
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑agent',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
      },
      {
        id: 'project-2',
        org_id: 'org-1',
        name: '第二项目',
        environment: 'development',
        department_id: 'research-direct',
        role: 'admin',
      },
    ]);

    render(<AdminPage />);

    expect(await screen.findByTestId('project-members-panel')).toHaveAttribute('data-project-id', 'project-1');
    await user.click(screen.getByRole('button', { name: /第二项目/ }));
    expect(screen.getByTestId('project-members-panel')).toHaveAttribute('data-project-id', 'project-2');
  });

  it('hydrates the member-management view from a direct or legacy URL', async () => {
    window.history.replaceState({}, '', '/admin?view=members');

    render(<AdminPage />);

    expect(await screen.findByTestId('team-directory-panel')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '成员管理' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('PROJECT PROFILE')).not.toBeInTheDocument();
  });

  it('keeps project initialization controls compact and visible in the primary workspace', async () => {
    render(<AdminPage />);

    const main = await screen.findByRole('main');
    expect(main).toHaveClass('py-3');
    expect(screen.getByTestId('project-create-profile-workspace')).toHaveClass('gap-3');
    expect(screen.getByRole('button', { name: '打开分类管理' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '创建项目' })).toBeInTheDocument();
  });

  it('uses a light project profile and only shows pending approval items', async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    expect(await screen.findByText('PROJECT PROFILE')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '项目资料' })).not.toBeInTheDocument();
    expect((await screen.findAllByText('待审批资料一')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('另一个项目的审批资料').length).toBeGreaterThan(0);
    expect(screen.queryByText('已审批资料不应显示')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '批准并入库' }));

    await waitFor(() => {
      expect(mocks.reviewProjectMemoryDraft).toHaveBeenCalledWith('pending-1', 'approve', '');
    });
    expect(screen.queryByText('待审批资料一')).not.toBeInTheDocument();
    expect(screen.getAllByText('另一个项目的审批资料').length).toBeGreaterThan(0);
  });

  it('shows an indeterminate progress dialog while an administrator approves materials into knowledge', async () => {
    let finishReview: (value: {
      id: string;
      status: 'approved';
      document_id: string;
      chunk_count: number;
      wiki_page_count: number;
    }) => void = () => undefined;
    mocks.reviewProjectMemoryDraft.mockImplementation(() => new Promise((resolve) => {
      finishReview = resolve;
    }));
    render(<AdminPage />);

    await screen.findAllByText('待审批资料一');
    fireEvent.click(screen.getByRole('button', { name: '批准并入库' }));

    const dialog = await screen.findByRole('dialog', { name: '审批入库处理中' });
    expect(dialog).toHaveTextContent('智慧大脑agent');
    expect(dialog).toHaveTextContent('待审批资料一');
    expect(dialog).toHaveTextContent('服务器正在校验提交内容并写入正式项目数据');
    expect(screen.getByRole('progressbar', { name: '审批入库进度' })).not.toHaveAttribute('aria-valuenow');
    expect(screen.getByRole('button', { name: '批准并入库' })).toBeDisabled();

    await act(async () => {
      finishReview({
        id: 'pending-1',
        status: 'approved',
        document_id: 'doc-new',
        chunk_count: 3,
        wiki_page_count: 1,
      });
    });

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '审批入库处理中' })).not.toBeInTheDocument();
    });
    expect(screen.queryByText('待审批资料一')).not.toBeInTheDocument();
  });

  it('refreshes the approval queue when another reviewer already processed the item', async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await screen.findAllByText('待审批资料一');
    mocks.reviewProjectMemoryDraft.mockRejectedValueOnce(
      new ApiError(409, { detail: 'draft already approved' }, 'draft already approved'),
    );
    mocks.listProjectMemoryReviewQueue.mockResolvedValueOnce([]);
    await user.click(screen.getByRole('button', { name: '批准并入库' }));

    expect(await screen.findByText('该资料已由其他审批人处理，审批列表已刷新')).toBeInTheDocument();
    await waitFor(() => expect(mocks.listProjectMemoryReviewQueue).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('待审批资料一')).not.toBeInTheDocument();
  });

  it('loads one approval queue across all authorized projects and labels project ownership', async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(mocks.listProjectMemoryReviewQueue).toHaveBeenCalled());
    await user.click(await screen.findByText('另一个项目的审批资料'));
    expect(screen.getAllByText('跨项目审批示例').length).toBeGreaterThan(0);
    expect(screen.getByText(/跨项目审批示例 · 产业侧 \/ 直属分级/)).toBeInTheDocument();
    expect(screen.getByText(/方案\.pptx/)).toBeInTheDocument();
  });

  it('keeps project management access and lower modules after saving a partial project response', async () => {
    const user = userEvent.setup();
    mocks.updateProject.mockResolvedValue({
      id: 'project-1',
      org_id: 'org-1',
      name: '智慧大脑agent（已保存）',
      environment: 'development',
      department_id: 'research-direct',
      role: null,
      completed_at: null,
    });

    render(<AdminPage />);

    const nameInput = await screen.findByLabelText('项目名称');
    await waitFor(() => expect(nameInput).toHaveValue('智慧大脑agent'));
    fireEvent.change(nameInput, { target: { value: '智慧大脑agent（已保存）' } });
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mocks.updateProject).toHaveBeenCalledWith('project-1', {
        name: '智慧大脑agent（已保存）',
        completed_at: null,
      });
    });
    expect(await screen.findByText('项目信息已保存')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument();
    expect(screen.getByText('所有项目待审批内容')).toBeInTheDocument();
    expect(screen.getAllByText('待审批资料一').length).toBeGreaterThan(0);
  });

  it('keeps the desktop create and profile workspace aligned to the project list card', async () => {
    render(<AdminPage />);

    const projectList = await screen.findByLabelText('项目纵向滑动列表');
    const projectListCard = projectList.closest('[data-project-list-card]');
    const projectWorkspace = screen.getByTestId('project-create-profile-workspace');
    const profile = screen.getByTestId('project-profile-card');

    expect(projectListCard).toHaveClass('h-full');
    expect(projectWorkspace).toHaveClass(
      'min-[1400px]:grid-cols-[minmax(240px,0.7fr)_minmax(360px,1.3fr)]',
      'min-[1400px]:items-stretch',
    );
    expect(profile).toHaveClass('h-full');
  });

  it('loads the global project catalog for a system administrator without direct project memberships', async () => {
    const globalProject = {
      id: 'global-project',
      org_id: 'org-2',
      name: '全局管理项目',
      environment: 'development',
      department_id: 'research-direct',
      role: 'owner' as const,
    };
    mocks.getMe.mockResolvedValue({
      user_id: 'system-admin-without-project-membership',
      email: 'sysadmin@local.dev',
      full_name: 'System Admin',
      is_system_admin: true,
      can_manage_projects: true,
      memberships: [],
    });
    mocks.listProjectCatalog.mockResolvedValue([globalProject]);
    mocks.listProjects.mockResolvedValue([]);

    render(<AdminPage />);

    expect((await screen.findAllByText('全局管理项目')).length).toBeGreaterThan(0);
    expect(mocks.listProjectCatalog).toHaveBeenCalledTimes(1);
    expect(mocks.listProjects).not.toHaveBeenCalled();
  });

  it('hides project creation from a system administrator other than hanshangbo', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'other-system-admin',
      email: 'sysadmin@local.dev',
      full_name: 'System Admin',
      is_system_admin: true,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'owner' }],
    });

    render(<AdminPage />);

    expect(await screen.findByText('PROJECT PROFILE')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '创建项目' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '创建项目' })).not.toBeInTheDocument();
  });

  it('keeps project creation available for hanshangbo in an empty category', async () => {
    const user = userEvent.setup();
    departments = [
      ...departments,
      { id: 'new-root', name: '新第一分级', sort_order: 20, parent_id: null, allows_projects: false, level: 1 },
      {
        id: 'new-root-direct',
        name: '直属分级',
        sort_order: 21,
        parent_id: 'new-root',
        parent_name: '新第一分级',
        allows_projects: true,
        level: 2,
        is_direct: true,
      },
    ];

    render(<AdminPage />);

    const firstLevelSelect = await screen.findByLabelText<HTMLSelectElement>('第一分级');
    await waitFor(() => {
      expect(firstLevelSelect).toBeEnabled();
      expect(Array.from(firstLevelSelect.options).some((option) => option.value === 'new-root')).toBe(true);
    });
    await user.selectOptions(firstLevelSelect, 'new-root');
    expect(await screen.findByText('当前分类没有项目')).toBeInTheDocument();
    expect(await screen.findByText('请选择或创建项目')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '创建项目' })).toBeInTheDocument();
  });

  it('selects a newly created first-level category for its next child and project', async () => {
    const user = userEvent.setup();
    mocks.createProjectMemoryDepartment.mockImplementationOnce(async (input) => {
      const root = {
        id: 'new-root',
        name: input.name,
        sort_order: 20,
        parent_id: null,
        allows_projects: false,
        level: 1,
      };
      const direct = {
        id: 'new-root-direct',
        name: '直属分级',
        sort_order: 21,
        parent_id: root.id,
        parent_name: root.name,
        allows_projects: true,
        level: 2,
        is_direct: true,
      };
      departments = [...departments, root, direct];
      return root;
    });

    render(<AdminPage />);

    await user.click(await screen.findByRole('button', { name: '打开分类管理' }));
    await user.type(screen.getByLabelText('第一分级名称'), '新第一分级');
    await user.click(screen.getByRole('button', { name: '新增分类' }));

    expect(await screen.findByText('第一分级 新第一分级 已创建')).toBeInTheDocument();
    expect(screen.getByLabelText('上级第一分级')).toHaveValue('new-root');
    expect(screen.getByLabelText('项目第一分级')).toHaveValue('new-root');
    expect(screen.getByLabelText('项目第二分级')).toHaveValue('new-root-direct');
  });

  it('loads the full project catalog for a non-system project administrator', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'project-owner-1',
      email: 'owner@local.dev',
      full_name: 'Project Owner',
      is_system_admin: false,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'owner' }],
    });

    render(<AdminPage />);

    expect((await screen.findAllByText('智慧大脑agent')).length).toBeGreaterThan(0);
    expect(mocks.listProjectCatalog).toHaveBeenCalledTimes(1);
    expect(mocks.listProjects).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: '创建项目' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '创建项目' })).not.toBeInTheDocument();
  });

  it('keeps exactly three project rows visible and scrolls the remaining projects vertically', async () => {
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'completed-alpha',
        org_id: 'org-1',
        name: 'Alpha completed',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
        completed_at: '2026-08-01',
      },
      {
        id: 'active-beta',
        org_id: 'org-1',
        name: 'Beta active',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
        completed_at: null,
      },
      {
        id: 'completed-charlie',
        org_id: 'org-1',
        name: 'Charlie completed',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
        completed_at: '2026-08-02',
      },
      {
        id: 'active-delta',
        org_id: 'org-1',
        name: 'Delta active',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
        completed_at: null,
      },
    ]);

    render(<AdminPage />);

    await screen.findByText('Beta active');
    const projectList = screen.getByLabelText('项目纵向滑动列表');
    const projectOrder = screen.getAllByRole('button')
      .map((button) => button.textContent || '')
      .filter((text) => /(?:active|completed)-(?:alpha|beta|charlie|delta)/.test(text))
      .map((text) => text.match(/(?:active|completed)-(?:alpha|beta|charlie|delta)/)?.[0]);

    expect(projectOrder).toEqual([
      'active-beta',
      'active-delta',
      'completed-alpha',
      'completed-charlie',
    ]);
    expect(projectList).toHaveClass('h-[336px]', 'overflow-y-auto');
    expect(screen.queryByRole('button', { name: '上一组项目' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '下一组项目' })).not.toBeInTheDocument();
  });

  it('does not reopen a completed project when confirmation is cancelled', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'completed-project',
        org_id: 'org-1',
        name: 'Completed project',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
        completed_at: '2026-08-01',
      },
    ]);

    render(<AdminPage />);

    await user.click(await screen.findByRole('button', { name: '恢复为进行中' }));

    expect(confirm).toHaveBeenCalledWith(
      '确认将项目“Completed project”恢复为进行中吗？这会清空结项日期。',
    );
    expect(mocks.updateProject).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it('reopens a completed project after confirmation and keeps it selected', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const completedProject = {
      id: 'completed-project',
      org_id: 'org-1',
      name: 'Completed project',
      environment: 'development',
      department_id: 'research-direct',
      role: 'owner',
      completed_at: '2026-08-01',
    };
    mocks.listProjectCatalog.mockResolvedValue([completedProject]);
    mocks.updateProject.mockResolvedValue({ ...completedProject, completed_at: null });

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('第一分级')).not.toBeDisabled();
      expect(screen.getByLabelText('第二分级')).toHaveValue('research-direct');
      expect(mocks.listProjectMemoryDrafts).toHaveBeenCalledWith('completed-project');
    });
    await user.click(screen.getByRole('button', { name: '恢复为进行中' }));

    await waitFor(() => {
      expect(mocks.updateProject).toHaveBeenCalledWith('completed-project', {
        completed_at: null,
      });
    });
    expect(await screen.findByText('项目已恢复为进行中')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Completed project' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '恢复为进行中' })).not.toBeInTheDocument();
    });
    confirm.mockRestore();
  });

  it('uses the fixed three-level project hierarchy without a free-form department creator', async () => {
    const user = userEvent.setup();
    departments = [
      { id: 'research', name: '研发支撑', sort_order: 10, parent_id: null, allows_projects: false, level: 1 },
      { id: 'research-direct', name: '直属分级', sort_order: 11, parent_id: 'research', parent_name: '研发支撑', allows_projects: true, level: 2, is_direct: true },
      { id: 'team-management', name: '团队管理', sort_order: 20, parent_id: null, allows_projects: false, level: 1 },
      { id: 'team-management-direct', name: '直属分级', sort_order: 21, parent_id: 'team-management', parent_name: '团队管理', allows_projects: true, level: 2, is_direct: true },
      { id: 'industry', name: '产业侧', sort_order: 30, parent_id: null, allows_projects: false, level: 1 },
      { id: 'industry-direct', name: '直属分级', sort_order: 30, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2, is_direct: true },
      { id: 'marketing', name: '市场', sort_order: 31, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2 },
      { id: 'business', name: '业务', sort_order: 32, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2 },
      { id: 'education', name: '教学侧', sort_order: 40, parent_id: null, allows_projects: false, level: 1 },
      { id: 'education-direct', name: '直属分级', sort_order: 41, parent_id: 'education', parent_name: '教学侧', allows_projects: true, level: 2, is_direct: true },
      { id: 'science', name: '科研侧', sort_order: 50, parent_id: null, allows_projects: false, level: 1 },
      { id: 'science-direct', name: '直属分级', sort_order: 51, parent_id: 'science', parent_name: '科研侧', allows_projects: true, level: 2, is_direct: true },
    ];
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑agent',
        environment: 'development',
        department_id: 'research-direct',
        role: 'owner',
      },
    ]);
    render(<AdminPage />);

    const firstLevel = await screen.findByLabelText('第一分级');
    const secondLevel = await screen.findByLabelText('第二分级');
    await waitFor(() => {
      expect(firstLevel).not.toBeDisabled();
      expect(secondLevel).toHaveValue('research-direct');
      expect(mocks.listProjectMemoryDrafts).toHaveBeenCalledWith('project-1');
    });
    expect(screen.queryByRole('heading', { name: '创建部门' })).not.toBeInTheDocument();
    expect(secondLevel).toHaveValue('research-direct');
    expect(screen.getAllByRole('option', { name: '研发支撑' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: '团队管理' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: '产业侧' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: '教学侧' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: '科研侧' }).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText('第一分级'), { target: { value: 'industry' } });
    expect(screen.getByLabelText('第一分级')).toHaveValue('industry');
    await waitFor(() => {
      expect(screen.getByLabelText('第一分级')).toHaveValue('industry');
      expect(screen.getByLabelText('第二分级')).toHaveValue('industry-direct');
      expect(screen.getAllByRole('option', { name: '直属分级' }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('option', { name: '市场' }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('option', { name: '业务' }).length).toBeGreaterThan(0);
    });
  });

  it('lets a project administrator transfer a project to another department', async () => {
    const user = userEvent.setup();
    departments = [
      { id: 'research', name: '研发支撑', sort_order: 10, parent_id: null, allows_projects: false, level: 1 },
      { id: 'research-direct', name: '直属分级', sort_order: 11, parent_id: 'research', parent_name: '研发支撑', allows_projects: true, level: 2, is_direct: true },
      { id: 'team-management', name: '团队管理', sort_order: 20, parent_id: null, allows_projects: false, level: 1 },
      { id: 'team-management-direct', name: '直属分级', sort_order: 21, parent_id: 'team-management', parent_name: '团队管理', allows_projects: true, level: 2, is_direct: true },
      { id: 'industry', name: '产业侧', sort_order: 30, parent_id: null, allows_projects: false, level: 1 },
      { id: 'industry-direct', name: '直属分级', sort_order: 30, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2, is_direct: true },
      { id: 'marketing', name: '市场', sort_order: 31, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2 },
      { id: 'business', name: '业务', sort_order: 32, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2 },
    ];
    mocks.getMe.mockResolvedValue({
      user_id: 'project-admin-1',
      email: 'project-admin@local.dev',
      full_name: 'project-admin',
      is_system_admin: false,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'business_user' }],
    });
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑agent',
        environment: 'development',
        department_id: 'research-direct',
        role: 'admin',
      },
    ]);
    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByText('PROJECT PROFILE')).toBeInTheDocument();
      expect(screen.getByLabelText('第一分级')).not.toBeDisabled();
      expect(screen.getByLabelText('第二分级')).toHaveValue('research-direct');
      expect(mocks.listProjectMemoryDrafts).toHaveBeenCalledWith('project-1');
    });
    expect(screen.queryByRole('button', { name: '删除项目' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '迁移分类' }));
    await user.selectOptions(screen.getByLabelText('目标第一分级'), 'industry');
    await user.selectOptions(screen.getByLabelText('目标第二分级'), 'business');
    expect(screen.getByText('项目原始资料')).toBeInTheDocument();
    expect(screen.getByText('项目 Wiki')).toBeInTheDocument();
    expect(screen.getByText('会议记录')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: '确认迁移项目知识库' }));
    await user.click(screen.getByRole('button', { name: '开始迁移' }));

    await waitFor(() => {
      expect(mocks.startProjectDepartmentMigration).toHaveBeenCalledWith('project-1', {
        target_department_id: 'business',
        expected_source_department_id: 'research-direct',
        migrate_knowledge_base: true,
      });
    });
    expect(await screen.findByText('项目分类与知识库已完成迁移')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('迁移完成')).toBeInTheDocument();
      expect(screen.getByLabelText('第一分级')).toHaveValue('industry');
      expect(screen.getByLabelText('第二分级')).toHaveValue('business');
    });
  });

  it('shows the real metadata-sync stage while a knowledge migration is running', async () => {
    const user = userEvent.setup();
    departments = [
      { id: 'research', name: '研发支撑', sort_order: 10, parent_id: null, allows_projects: false, level: 1 },
      { id: 'research-direct', name: '直属分级', sort_order: 11, parent_id: 'research', parent_name: '研发支撑', allows_projects: true, level: 2, is_direct: true },
      { id: 'industry', name: '产业侧', sort_order: 30, parent_id: null, allows_projects: false, level: 1 },
      { id: 'industry-direct', name: '直属分级', sort_order: 30, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2, is_direct: true },
      { id: 'business', name: '业务', sort_order: 32, parent_id: 'industry', parent_name: '产业侧', allows_projects: true, level: 2 },
    ];
    mocks.getMe.mockResolvedValue({
      user_id: 'project-admin-1',
      email: 'project-admin@local.dev',
      full_name: 'project-admin',
      is_system_admin: false,
      can_manage_projects: true,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'business_user' }],
    });
    mocks.listProjectCatalog.mockResolvedValue([{
      id: 'project-1',
      org_id: 'org-1',
      name: '智慧大脑agent',
      environment: 'development',
      department_id: 'research-direct',
      role: 'admin',
    }]);
    mocks.startProjectDepartmentMigration.mockResolvedValue({
      id: 'migration-1',
      project_id: 'project-1',
      source_department_id: 'research-direct',
      target_department_id: 'business',
      status: 'running',
      progress: 10,
      current_step: 'inventory',
      raw_material_count: 2,
      wiki_page_count: 3,
      meeting_record_count: 1,
      verified: false,
    });
    mocks.getProjectDepartmentMigration
      .mockResolvedValueOnce({
        id: 'migration-1',
        project_id: 'project-1',
        source_department_id: 'research-direct',
        target_department_id: 'business',
        status: 'running',
        progress: 55,
        current_step: 'syncing_metadata',
        raw_material_count: 2,
        wiki_page_count: 3,
        meeting_record_count: 1,
        verified: false,
      })
      .mockResolvedValueOnce({
        id: 'migration-1',
        project_id: 'project-1',
        source_department_id: 'research-direct',
        target_department_id: 'business',
        status: 'completed',
        progress: 100,
        current_step: 'completed',
        raw_material_count: 2,
        wiki_page_count: 3,
        meeting_record_count: 1,
        verified: true,
      });

    render(<AdminPage />);
    await waitFor(() => expect(screen.getByText('PROJECT PROFILE')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '迁移分类' }));
    await user.selectOptions(screen.getByLabelText('目标第一分级'), 'industry');
    await user.selectOptions(screen.getByLabelText('目标第二分级'), 'business');
    await user.click(screen.getByRole('checkbox', { name: '确认迁移项目知识库' }));
    await user.click(screen.getByRole('button', { name: '开始迁移' }));

    expect(await screen.findByText('同步分类元数据')).toBeInTheDocument();
    expect(await screen.findByText('项目分类与知识库已完成迁移')).toBeInTheDocument();
  });

  it('redirects ordinary members away from project management and keeps request APIs dormant', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'member-1',
      email: 'member@local.dev',
      full_name: 'member',
      is_system_admin: false,
      can_manage_projects: false,
      memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'business_user' }],
    });
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '现有项目',
        environment: 'development',
        department_id: 'research-direct',
        role: 'business_user',
      },
    ]);
    render(<AdminPage />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith('/profile'));
    expect(mocks.listProjectCatalog).not.toHaveBeenCalled();
    expect(mocks.listProjects).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: '申请新增项目' })).not.toBeInTheDocument();
    expect(mocks.listProjectCreationRequests).not.toHaveBeenCalled();
    expect(mocks.submitProjectCreationRequest).not.toHaveBeenCalled();
  });

  it('does not infer project-management access from ownership of a private organization', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'member-with-private-org',
      email: 'member-with-private-org@local.dev',
      full_name: 'member-with-private-org',
      is_system_admin: false,
      can_manage_projects: false,
      memberships: [
        { org_id: 'private-org', org_name: 'Private organization', role: 'owner' },
        { org_id: 'org-1', org_name: 'Business organization', role: 'business_user' },
      ],
    });
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: 'Existing business project',
        environment: 'development',
        department_id: 'research-direct',
        role: 'business_user',
      },
    ]);

    render(<AdminPage />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith('/profile'));
    expect(screen.queryByRole('heading', { name: '创建项目' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '申请新增项目' })).not.toBeInTheDocument();
    expect(mocks.submitProjectCreationRequest).not.toHaveBeenCalled();
  });

  it('opens category management in a separate dialog and keeps it out of the page flow', async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    const openButton = await screen.findByRole('button', { name: '打开分类管理' });
    expect(screen.queryByRole('dialog', { name: '分类管理' })).not.toBeInTheDocument();

    await user.click(openButton);
    expect(screen.getByRole('dialog', { name: '分类管理' })).toBeInTheDocument();
    expect(screen.getByText('系统分级 · 自动维护')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '改名' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '删除分类' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: '拖动排序 研发支撑' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '拖动排序 直属分级' })).toBeEnabled();
    expect(screen.queryByRole('spinbutton', { name: /分类排序/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '关闭分类管理' }));
    expect(screen.queryByRole('dialog', { name: '分类管理' })).not.toBeInTheDocument();
  });

  it('hides administrator project request approval and material upload modules', async () => {
    mocks.listProjectCreationRequests.mockResolvedValue([
      {
        id: 'request-1',
        requester_id: 'member-1',
        requester_username: 'member',
        org_id: 'org-1',
        org_name: '智慧大脑',
        name: '新材料平台',
        environment: 'development',
        department_id: 'research',
        department_name: '研发',
        completed_at: '2026-12-31',
        reason: '需要独立管理研发资料',
        status: 'pending',
        created_at: '2026-08-10T09:00:00Z',
      },
    ]);
    mocks.reviewProjectCreationRequest.mockResolvedValue({
      id: 'request-1',
      requester_id: 'member-1',
      requester_username: 'member',
      org_id: 'org-1',
      org_name: '智慧大脑',
      name: '新材料平台',
      environment: 'development',
      department_id: 'research',
      department_name: '研发',
      completed_at: '2026-12-31',
      reason: '需要独立管理研发资料',
      status: 'approved',
      review_comment: '同意立项',
      created_project_id: 'project-2',
      created_at: '2026-08-10T09:00:00Z',
      reviewed_at: '2026-08-10T10:00:00Z',
    });

    render(<AdminPage />);
    await screen.findByText('PROJECT PROFILE');
    expect(screen.queryByRole('heading', { name: '项目申请审批' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '上传项目资料' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'GitHub 仓库' })).not.toBeInTheDocument();
    expect(mocks.reviewProjectCreationRequest).not.toHaveBeenCalled();
  });
});
