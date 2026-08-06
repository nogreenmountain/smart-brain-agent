import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MembersPage from './page';

const mocks = vi.hoisted(() => ({
  addProjectMember: vi.fn(),
  getMe: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectMembers: vi.fn(),
  listProjectCatalog: vi.fn(),
  removeProjectMember: vi.fn(),
  replace: vi.fn(),
  resetProjectMemberPassword: vi.fn(),
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
    removeProjectMember: mocks.removeProjectMember,
    resetProjectMemberPassword: mocks.resetProjectMemberPassword,
  };
});

describe('MembersPage', () => {
  let currentMembers: {
    user_id: string;
    email: string;
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
    mocks.removeProjectMember.mockReset();
    mocks.replace.mockReset();
    mocks.resetProjectMemberPassword.mockReset();
    currentMembers = [
      {
        user_id: 'admin-1',
        email: 'hanshangbo@local.dev',
        nickname: '研发负责人',
        display_name: '研发负责人',
        role: 'owner',
      },
    ];
    mocks.getMe.mockResolvedValue({
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      full_name: 'Admin',
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
    mocks.listProjectMembers.mockImplementation(async () => currentMembers);
    mocks.addProjectMember.mockImplementation(async () => {
      currentMembers = [
        ...currentMembers,
        {
          user_id: 'user-2',
          email: 'test2@local.dev',
          role: 'developer',
        },
      ];
      return {
        user_id: 'user-2',
        email: 'test2@local.dev',
        role: 'developer',
      };
    });
    mocks.removeProjectMember.mockImplementation(async (_projectId: string, userId: string) => {
      currentMembers = currentMembers.filter((member) => member.user_id !== userId);
    });
    mocks.resetProjectMemberPassword.mockResolvedValue({
      user_id: 'user-2',
      email: 'test2@local.dev',
      status: 'updated',
    });
  });

  it('adds a project member by short username', async () => {
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员管理' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '研发' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '智慧大脑 (development)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '市场素材库 (development)' })).not.toBeInTheDocument();
    expect((await screen.findAllByText('hanshangbo@local.dev')).length).toBeGreaterThan(0);
    expect(screen.getByText('研发负责人')).toBeInTheDocument();
    expect(screen.getByText('账号不存在时会自动创建，初始密码 123456。')).toBeInTheDocument();
    const roleSelect = screen.getByLabelText('成员角色');
    expect(within(roleSelect).getByRole('option', { name: '项目成员' })).toBeInTheDocument();
    expect(within(roleSelect).getByRole('option', { name: '项目负责人' })).toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '普通成员' })).not.toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '研发成员' })).not.toBeInTheDocument();
    expect(within(roleSelect).queryByRole('option', { name: '项目管理员' })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('用户名或邮箱'), 'test2');
    await user.selectOptions(roleSelect, 'developer');
    await user.click(screen.getByRole('button', { name: '添加成员' }));

    await waitFor(() => {
      expect(mocks.addProjectMember).toHaveBeenCalledWith('project-1', {
        identifier: 'test2',
        role: 'developer',
      });
    });
    expect(await screen.findByText('test2@local.dev')).toBeInTheDocument();
  });

  it('filters projects by department before loading members', async () => {
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员管理' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('选择部门'), 'marketing');

    await waitFor(() => {
      expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-2');
    });
    expect(screen.getByRole('option', { name: '市场素材库 (development)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '智慧大脑 (development)' })).not.toBeInTheDocument();
  });

  it('removes a member from the selected project', async () => {
    currentMembers = [
      ...currentMembers,
      { user_id: 'user-2', email: 'test2@local.dev', role: 'business_user' },
    ];
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByText('test2@local.dev')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '删除 test2@local.dev' }));

    await waitFor(() => {
      expect(mocks.removeProjectMember).toHaveBeenCalledWith('project-1', 'user-2');
    });
    await waitFor(() => {
      expect(screen.queryByText('test2@local.dev')).not.toBeInTheDocument();
    });
  });

  it('resets a member login password', async () => {
    currentMembers = [
      ...currentMembers,
      { user_id: 'user-2', email: 'test2@local.dev', role: 'business_user' },
    ];
    const user = userEvent.setup();
    render(<MembersPage />);

    expect(await screen.findByText('test2@local.dev')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '修改 test2@local.dev 密码' }));
    await user.type(screen.getByLabelText('新登录密码'), '654321');
    await user.click(screen.getByRole('button', { name: '保存新密码' }));

    await waitFor(() => {
      expect(mocks.resetProjectMemberPassword).toHaveBeenCalledWith(
        'project-1',
        'user-2',
        '654321',
      );
    });
    expect(screen.queryByText('654321')).not.toBeInTheDocument();
  });

  it('lets regular project members view the roster without management actions', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'user-2',
      email: 'test2@local.dev',
      full_name: 'Test 2',
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
    ]);
    currentMembers = [
      { user_id: 'admin-1', email: 'hanshangbo@local.dev', role: 'owner' },
      { user_id: 'user-2', email: 'test2@local.dev', role: 'developer' },
    ];

    render(<MembersPage />);

    expect(await screen.findByRole('heading', { name: '成员管理' })).toBeInTheDocument();
    expect(await screen.findByText('hanshangbo@local.dev')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText('test2@local.dev').length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText('项目负责人').length).toBeGreaterThan(0);
    expect(screen.getAllByText('项目成员').length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('用户名或邮箱')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '删除 test2@local.dev' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修改 test2@local.dev 密码' })).not.toBeInTheDocument();
  });
});
