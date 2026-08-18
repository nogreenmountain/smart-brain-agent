import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MembersPage from './page';

vi.mock('@/components/management-workspace/TeamDirectoryPanel', () => ({
  TeamDirectoryPanel: () => <div>团队账号维护</div>,
}));

const mocks = vi.hoisted(() => ({
  addProjectMember: vi.fn(),
  getMe: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectMembers: vi.fn(),
  listProjectCatalog: vi.fn(),
  listProjects: vi.fn(),
  listProjectMemberOptions: vi.fn(),
  removeProjectMember: vi.fn(),
  replace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: mocks.replace,
  }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    addProjectMember: mocks.addProjectMember,
    getMe: mocks.getMe,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjectMembers: mocks.listProjectMembers,
    listProjectCatalog: mocks.listProjectCatalog,
    listProjects: mocks.listProjects,
    listProjectMemberOptions: mocks.listProjectMemberOptions,
    removeProjectMember: mocks.removeProjectMember,
  };
});

describe('MembersPage', () => {
  let currentMembers: {
    user_id: string;
    email: string;
    username: string;
    nickname?: string | null;
    display_name?: string;
    role: 'owner' | 'admin' | 'developer' | 'business_user';
  }[];

  beforeEach(() => {
    mocks.addProjectMember.mockReset();
    mocks.getMe.mockReset();
    mocks.listProjectMemoryDepartments.mockReset();
    mocks.listProjectMembers.mockReset();
    mocks.listProjectCatalog.mockReset();
    mocks.listProjects.mockReset();
    mocks.listProjectMemberOptions.mockReset();
    mocks.removeProjectMember.mockReset();
    mocks.replace.mockReset();
    currentMembers = [
      {
        user_id: 'admin-1',
        email: 'hanshangbo@local.dev',
        username: 'hanshangbo',
        nickname: '研发负责人',
        display_name: '研发负责人',
        role: 'owner',
      },
    ];
    mocks.getMe.mockResolvedValue({
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      full_name: 'Admin',
      is_system_admin: true,
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'owner' }],
    });
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发', sort_order: 1 },
      { id: 'marketing', name: '市场', sort_order: 2 },
      { id: 'business', name: '业务', sort_order: 3 },
    ]);
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'owner',
      },
      {
        id: 'project-2',
        org_id: 'org-1',
        name: '市场素材库',
        environment: 'development',
        department_id: 'marketing',
        role: 'owner',
      },
    ]);
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'owner',
      },
    ]);
    mocks.listProjectMembers.mockImplementation(async () => currentMembers);
    mocks.listProjectMemberOptions.mockResolvedValue([
      {
        user_id: 'admin-1',
        email: 'hanshangbo@local.dev',
        username: 'hanshangbo',
        nickname: '研发负责人',
        display_name: '研发负责人',
        is_active: true,
        is_system_admin: true,
        project_count: 2,
      },
      {
        user_id: 'user-2',
        email: 'test2@local.dev',
        username: 'test2',
        nickname: '测试成员',
        display_name: '测试成员',
        is_active: true,
        is_system_admin: false,
        project_count: 0,
      },
    ]);
    mocks.addProjectMember.mockImplementation(async () => {
      currentMembers = [
        ...currentMembers,
        {
          user_id: 'user-2',
          email: 'test2@local.dev',
          username: 'test2',
          role: 'developer',
        },
      ];
      return {
        user_id: 'user-2',
        email: 'test2@local.dev',
        username: 'test2',
        role: 'developer',
      };
    });
    mocks.removeProjectMember.mockImplementation(async (_projectId: string, userId: string) => {
      currentMembers = currentMembers.filter((member) => member.user_id !== userId);
    });
  });

  it('adds an existing active team member to the selected project', async () => {
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员管理' })).toBeInTheDocument();
    expect(screen.getByText('团队账号维护')).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: '研发' })).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: '智慧大脑 (development)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '市场素材库 (development)' })).not.toBeInTheDocument();
    expect(await screen.findByText('研发负责人')).toBeInTheDocument();
    expect(await screen.findByText('账号：hanshangbo')).toBeInTheDocument();
    expect(screen.queryByText('hanshangbo@local.dev')).not.toBeInTheDocument();
    expect(screen.getByText('这里只能选择团队管理中已启用的成员。')).toBeInTheDocument();
    expect(screen.queryByLabelText('用户名或邮箱')).not.toBeInTheDocument();
    const roleSelect = screen.getByLabelText('成员角色');
    expect(within(roleSelect).getByRole('option', { name: '项目成员' })).toBeInTheDocument();
    expect(within(roleSelect).getByRole('option', { name: '项目负责人' })).toBeInTheDocument();
    expect(within(roleSelect).getByRole('option', { name: '总负责人' })).toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '普通成员' })).not.toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '研发成员' })).not.toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '项目管理员' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('项目筛选')).toHaveClass('min-w-0');
    expect(screen.getByRole('form', { name: '添加项目成员' })).toHaveClass('min-w-0');
    expect(screen.getByRole('button', { name: '添加成员' })).toHaveClass('w-full');

    await user.selectOptions(screen.getByLabelText('选择团队成员'), 'user-2');
    await user.selectOptions(roleSelect, 'developer');
    await user.click(screen.getByRole('button', { name: '添加成员' }));

    await waitFor(() => {
      expect(mocks.addProjectMember).toHaveBeenCalledWith('project-1', {
        user_id: 'user-2',
        role: 'developer',
      });
    });
    expect(await screen.findByText('test2')).toBeInTheDocument();
    expect(screen.queryByText('test2@local.dev')).not.toBeInTheDocument();
  });

  it('filters addable team members by a single nickname or account character', async () => {
    mocks.listProjectMemberOptions.mockResolvedValue([
      {
        user_id: 'user-tang',
        email: 'tangweixiang@local.dev',
        username: 'tangweixiang',
        nickname: '唐伟翔',
        display_name: '唐伟翔',
        is_active: true,
        is_system_admin: false,
        project_count: 0,
      },
      {
        user_id: 'user-wu',
        email: 'wuyuchen@local.dev',
        username: 'wuyuchen',
        nickname: '吴昱辰',
        display_name: '吴昱辰',
        is_active: true,
        is_system_admin: false,
        project_count: 0,
      },
    ]);
    const user = userEvent.setup();
    render(<MembersPage />);

    const search = await screen.findByLabelText('搜索团队成员');
    await user.type(search, '唐');

    const memberSelect = screen.getByLabelText('选择团队成员');
    expect(within(memberSelect).getByRole('option', { name: '唐伟翔（账号：tangweixiang）' })).toBeInTheDocument();
    expect(within(memberSelect).queryByRole('option', { name: '吴昱辰（账号：wuyuchen）' })).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'u');
    expect(within(memberSelect).getByRole('option', { name: '吴昱辰（账号：wuyuchen）' })).toBeInTheDocument();
  });

  it('filters projects by department before loading members', async () => {
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员管理' })).toBeInTheDocument();
    await screen.findByRole('option', { name: '市场' });
    await user.selectOptions(screen.getByLabelText('第一分级'), 'marketing');

    await waitFor(() => {
      expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-2');
    });
    expect(screen.getByRole('option', { name: '市场素材库 (development)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '智慧大脑 (development)' })).not.toBeInTheDocument();
  });

  it('selects a project through the complete first-level hierarchy', async () => {
    const user = userEvent.setup();
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: true, level: 1 },
      { id: 'industry', name: '产业侧', sort_order: 2, parent_id: null, allows_projects: false, level: 1 },
      { id: 'marketing', name: '市场', sort_order: 1, parent_id: 'industry', allows_projects: true, level: 2 },
    ]);

    render(<MembersPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('第一分级')).toHaveValue('research');
    });
    expect(mocks.listProjectMemoryDepartments).toHaveBeenCalledWith(true);

    await user.selectOptions(screen.getByLabelText('第一分级'), 'industry');

    expect(await screen.findByLabelText('第二分级')).toHaveValue('marketing');
    await waitFor(() => {
      expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-2');
    });
  });

  it('removes a member from the selected project', async () => {
    currentMembers = [
      ...currentMembers,
      { user_id: 'user-2', email: 'test2@local.dev', username: 'test2', role: 'business_user' },
    ];
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByText('test2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '移出项目 test2' }));

    await waitFor(() => {
      expect(mocks.removeProjectMember).toHaveBeenCalledWith('project-1', 'user-2');
    });
    await waitFor(() => {
      expect(screen.queryByText('test2')).not.toBeInTheDocument();
    });
  });

  it('does not expose account creation, username, or password operations', async () => {
    currentMembers = [
      ...currentMembers,
      { user_id: 'user-2', email: 'wuyichen@local.dev', username: 'wuyichen', role: 'business_user' },
    ];
    render(<MembersPage />);

    expect(await screen.findByText('wuyichen')).toBeInTheDocument();
    expect(screen.queryByText('wuyichen@local.dev')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修改 wuyichen 用户名' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修改 wuyichen 密码' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('新登录用户名')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('新登录密码')).not.toBeInTheDocument();
  });

  it('lets regular project members view the roster without management actions', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'user-2',
      email: 'test2@local.dev',
      full_name: 'Test 2',
      is_system_admin: false,
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'business_user' }],
    });
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'developer',
      },
      {
        id: 'project-2',
        org_id: 'org-1',
        name: '市场素材库',
        environment: 'development',
        department_id: 'marketing',
        role: undefined,
      },
    ]);
    currentMembers = [
      { user_id: 'admin-1', email: 'hanshangbo@local.dev', username: 'hanshangbo', role: 'owner' },
      { user_id: 'user-2', email: 'test2@local.dev', username: 'test2', role: 'developer' },
    ];

    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员信息' })).toBeInTheDocument();
    expect(await screen.findByText('hanshangbo')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText('test2').length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText('总负责人').length).toBeGreaterThan(0);
    expect(screen.getAllByText('项目成员').length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('用户名或邮箱')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '移出项目 test2' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修改 test2 密码' })).not.toBeInTheDocument();
    expect(mocks.listProjectCatalog).toHaveBeenCalledTimes(1);
    expect(mocks.listProjects).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('第一分级'), 'marketing');
    expect(await screen.findByRole('option', { name: '市场素材库 (development)' })).toBeInTheDocument();
    await waitFor(() => expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-2'));
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
  });

  it('shows the full catalog to a project administrator but only manages their own project', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'project-admin-1',
      email: 'project-admin@local.dev',
      full_name: 'Project Admin',
      is_system_admin: false,
      memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'admin' }],
    });
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '负责项目',
        environment: 'development',
        department_id: 'research',
        role: 'admin',
      },
      {
        id: 'project-secret',
        org_id: 'org-secret',
        name: '其他项目',
        environment: 'production',
        department_id: 'marketing',
        role: undefined,
      },
    ]);

    render(<MembersPage />);

    expect(await screen.findByRole('option', { name: '负责项目 (development)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '添加成员' })).toBeInTheDocument();
    expect(mocks.listProjectCatalog).toHaveBeenCalledTimes(1);
    expect(mocks.listProjects).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('第一分级'), 'marketing');
    expect(await screen.findByRole('option', { name: '其他项目 (production)' })).toBeInTheDocument();
    await waitFor(() => expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-secret'));
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
  });

  it('keeps the global project catalog available to system administrators', async () => {
    render(<MembersPage />);

    expect(await screen.findByRole('option', { name: '智慧大脑 (development)' })).toBeInTheDocument();
    expect(mocks.listProjectCatalog).toHaveBeenCalledTimes(1);
    expect(mocks.listProjects).not.toHaveBeenCalled();
  });
});
