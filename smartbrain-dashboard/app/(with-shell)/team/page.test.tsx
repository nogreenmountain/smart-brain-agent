import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TeamPage from './page';

const mocks = vi.hoisted(() => ({
  createTeamMember: vi.fn(),
  deactivateTeamMember: vi.fn(),
  getMe: vi.fn(),
  listTeamMembers: vi.fn(),
  reactivateTeamMember: vi.fn(),
  renameTeamMemberUsername: vi.fn(),
  replace: vi.fn(),
  resetTeamMemberPassword: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createTeamMember: mocks.createTeamMember,
    deactivateTeamMember: mocks.deactivateTeamMember,
    getMe: mocks.getMe,
    listTeamMembers: mocks.listTeamMembers,
    reactivateTeamMember: mocks.reactivateTeamMember,
    renameTeamMemberUsername: mocks.renameTeamMemberUsername,
    resetTeamMemberPassword: mocks.resetTeamMemberPassword,
  };
});

describe('TeamPage', () => {
  let teamMembers: Array<{
    user_id: string;
    email: string;
    username: string;
    nickname?: string | null;
    display_name: string;
    is_active: boolean;
    is_system_admin: boolean;
    project_count: number;
    created_at?: string | null;
    deactivated_at?: string | null;
  }>;

  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    teamMembers = [
      {
        user_id: 'admin-1',
        email: 'hanshangbo@local.dev',
        username: 'hanshangbo',
        nickname: '韩尚博',
        display_name: '韩尚博',
        is_active: true,
        is_system_admin: true,
        project_count: 5,
      },
      {
        user_id: 'user-2',
        email: 'member@local.dev',
        username: 'member',
        nickname: null,
        display_name: 'member',
        is_active: true,
        is_system_admin: false,
        project_count: 2,
      },
    ];
    mocks.getMe.mockResolvedValue({
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      full_name: 'Admin',
      is_system_admin: true,
      memberships: [],
    });
    mocks.listTeamMembers.mockImplementation(async () => teamMembers);
    mocks.createTeamMember.mockImplementation(async (input) => {
      const created = {
        user_id: 'user-3',
        email: `${input.username}@local.dev`,
        username: input.username,
        nickname: input.nickname,
        display_name: input.nickname || input.username,
        is_active: true,
        is_system_admin: false,
        project_count: 0,
      };
      teamMembers = [...teamMembers, created];
      return created;
    });
    mocks.deactivateTeamMember.mockImplementation(async (userId: string) => {
      teamMembers = teamMembers.map((member) =>
        member.user_id === userId
          ? { ...member, is_active: false, project_count: 0 }
          : member,
      );
    });
  });

  it('creates and deactivates SmartBrain team members from one system-admin page', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<TeamPage />);

    expect(await screen.findByRole('heading', { name: '团队管理' })).toBeInTheDocument();
    expect(await screen.findByText('韩尚博')).toBeInTheDocument();
    expect(screen.getByText('账号：hanshangbo')).toBeInTheDocument();
    expect(screen.getByText('已加入 5 个项目')).toBeInTheDocument();

    await user.type(screen.getByLabelText('用户名'), 'newmember');
    await user.type(screen.getByLabelText('昵称'), '新成员');
    await user.type(screen.getByLabelText('初始密码'), '654321');
    await user.click(screen.getByRole('button', { name: '创建团队成员' }));

    await waitFor(() => {
      expect(mocks.createTeamMember).toHaveBeenCalledWith({
        username: 'newmember',
        nickname: '新成员',
        password: '654321',
      });
    });
    expect(await screen.findByText('新成员')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '移出团队 member' }));
    await waitFor(() => {
      expect(mocks.deactivateTeamMember).toHaveBeenCalledWith('user-2');
    });
    expect(await screen.findByText('已停用')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '恢复成员 member' })).toBeInTheDocument();
  });

  it('moves account-level username and password actions out of project membership', async () => {
    const user = userEvent.setup();
    mocks.renameTeamMemberUsername.mockResolvedValue({
      ...teamMembers[1],
      username: 'renamed',
      email: 'renamed@local.dev',
    });
    mocks.resetTeamMemberPassword.mockResolvedValue({
      user_id: 'user-2',
      email: 'member@local.dev',
      status: 'updated',
    });
    render(<TeamPage />);

    expect(await screen.findByText('member')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '修改 member 用户名' }));
    const username = screen.getByLabelText('新登录用户名');
    await user.clear(username);
    await user.type(username, 'renamed');
    await user.click(screen.getByRole('button', { name: '保存用户名' }));
    await waitFor(() => {
      expect(mocks.renameTeamMemberUsername).toHaveBeenCalledWith('user-2', 'renamed');
    });

    await user.click(screen.getByRole('button', { name: '修改 member 密码' }));
    await user.type(screen.getByLabelText('新登录密码'), '7654321');
    await user.click(screen.getByRole('button', { name: '保存新密码' }));
    await waitFor(() => {
      expect(mocks.resetTeamMemberPassword).toHaveBeenCalledWith('user-2', '7654321');
    });
  });

  it('redirects non-system-admin users away from team management', async () => {
    mocks.getMe.mockResolvedValue({
      user_id: 'user-2',
      email: 'member@local.dev',
      full_name: 'Member',
      is_system_admin: false,
      memberships: [{ org_id: 'org-1', org_name: '研发', role: 'owner' }],
    });

    render(<TeamPage />);

    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith('/chat');
    });
    expect(mocks.listTeamMembers).not.toHaveBeenCalled();
  });
});
