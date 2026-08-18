import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectMembersPanel } from './ProjectMembersPanel';
import type { ProjectMember } from '@/lib/api';

const mocks = vi.hoisted(() => ({
  addProjectMember: vi.fn(),
  listProjectMemberOptions: vi.fn(),
  listProjectMembers: vi.fn(),
  removeProjectMember: vi.fn(),
  replace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    addProjectMember: mocks.addProjectMember,
    listProjectMemberOptions: mocks.listProjectMemberOptions,
    listProjectMembers: mocks.listProjectMembers,
    removeProjectMember: mocks.removeProjectMember,
  };
});

const currentUser = {
  user_id: 'admin-1',
  email: 'hanshangbo@local.dev',
  full_name: 'hanshangbo',
  is_system_admin: true,
  can_manage_projects: true,
  memberships: [{ org_id: 'org-1', org_name: '智慧大脑', role: 'owner' as const }],
};

const projectOne = {
  id: 'project-1',
  org_id: 'org-1',
  name: '智慧大脑agent',
  environment: 'development',
  department_id: 'research-direct',
  role: 'owner' as const,
};

describe('ProjectMembersPanel', () => {
  let members: ProjectMember[] = [
    {
      user_id: 'admin-1',
      email: 'hanshangbo@local.dev',
      username: 'hanshangbo',
      nickname: '韩尚博',
      display_name: '韩尚博',
      role: 'owner' as const,
    },
  ];

  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    members = [
      {
        user_id: 'admin-1',
        email: 'hanshangbo@local.dev',
        username: 'hanshangbo',
        nickname: '韩尚博',
        display_name: '韩尚博',
        role: 'owner',
      },
    ];
    mocks.listProjectMembers.mockImplementation(async () => members);
    mocks.listProjectMemberOptions.mockResolvedValue([
      {
        user_id: 'user-2',
        email: 'tangweixiang@local.dev',
        username: 'tangweixiang',
        nickname: '唐伟翔',
        display_name: '唐伟翔',
        is_active: true,
        is_system_admin: false,
        project_count: 0,
      },
    ]);
    mocks.addProjectMember.mockImplementation(async (_projectId, input) => {
      members = [
        ...members,
        {
          user_id: input.user_id,
          email: 'tangweixiang@local.dev',
          username: 'tangweixiang',
          nickname: '唐伟翔',
          display_name: '唐伟翔',
          role: input.role,
        },
      ];
    });
    mocks.removeProjectMember.mockImplementation(async (_projectId, userId) => {
      members = members.filter((member) => member.user_id !== userId);
    });
  });

  it('loads the selected project roster and lets an administrator add and remove a member', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<ProjectMembersPanel project={projectOne} currentUser={currentUser} canManage />);

    expect(await screen.findByRole('heading', { name: '智慧大脑agent 项目成员' })).toBeInTheDocument();
    expect(await screen.findByText('韩尚博')).toBeInTheDocument();
    expect(mocks.listProjectMembers).toHaveBeenCalledWith('project-1');
    expect(mocks.listProjectMemberOptions).toHaveBeenCalledWith('project-1');
    expect(screen.getAllByText('总负责人').length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText('搜索团队成员'), '唐');
    const memberSelect = screen.getByLabelText('选择团队成员');
    expect(within(memberSelect).getByRole('option', { name: '唐伟翔（账号：tangweixiang）' })).toBeInTheDocument();
    await user.selectOptions(memberSelect, 'user-2');
    await user.selectOptions(screen.getByLabelText('成员角色'), 'owner');
    await user.click(screen.getByRole('button', { name: '添加成员' }));

    await waitFor(() => {
      expect(mocks.addProjectMember).toHaveBeenCalledWith('project-1', {
        user_id: 'user-2',
        role: 'owner',
      });
    });
    expect(await screen.findByText('唐伟翔')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '移出项目 tangweixiang' }));
    await waitFor(() => expect(mocks.removeProjectMember).toHaveBeenCalledWith('project-1', 'user-2'));
    await waitFor(() => expect(screen.queryByText('唐伟翔')).not.toBeInTheDocument());
  });

  it('shows three project roles while preventing a project lead from assigning the overall lead', async () => {
    const { rerender } = render(
      <ProjectMembersPanel project={projectOne} currentUser={currentUser} canManage />,
    );
    await screen.findByText('韩尚博');

    const ownerRoleSelect = screen.getByLabelText('成员角色');
    expect(within(ownerRoleSelect).getByRole('option', { name: '总负责人' })).toBeInTheDocument();
    expect(within(ownerRoleSelect).getByRole('option', { name: '项目负责人' })).toBeInTheDocument();
    expect(within(ownerRoleSelect).getByRole('option', { name: '项目成员' })).toBeInTheDocument();

    rerender(
      <ProjectMembersPanel
        project={{ ...projectOne, role: 'admin' }}
        currentUser={{ ...currentUser, is_system_admin: false }}
        canManage
      />,
    );
    await waitFor(() => expect(mocks.listProjectMembers).toHaveBeenCalled());
    const leaderRoleSelect = screen.getByLabelText('成员角色');
    expect(within(leaderRoleSelect).queryByRole('option', { name: '总负责人' })).not.toBeInTheDocument();
    expect(within(leaderRoleSelect).getByRole('option', { name: '项目负责人' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '移出项目 hanshangbo' })).not.toBeInTheDocument();
  });

  it('is read-only for a regular project member and never loads addable team accounts', async () => {
    const memberUser = { ...currentUser, user_id: 'user-2', is_system_admin: false, can_manage_projects: false };
    members = [
      ...members,
      {
        user_id: 'user-2',
        email: 'member@local.dev',
        username: 'member',
        nickname: '普通成员',
        display_name: '普通成员',
        role: 'developer',
      },
    ];

    render(<ProjectMembersPanel project={{ ...projectOne, role: 'developer' }} currentUser={memberUser} canManage={false} />);

    expect(await screen.findByText('普通成员')).toBeInTheDocument();
    expect(screen.queryByLabelText('搜索团队成员')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByText('移出项目')).not.toBeInTheDocument();
    expect(mocks.listProjectMemberOptions).not.toHaveBeenCalled();
  });

  it('reloads the roster when the project changes and protects the current account', async () => {
    const { rerender } = render(
      <ProjectMembersPanel project={projectOne} currentUser={currentUser} canManage />,
    );
    expect(await screen.findByText('韩尚博')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '不能移出当前账号 hanshangbo' })).toBeDisabled();

    rerender(
      <ProjectMembersPanel
        project={{ ...projectOne, id: 'project-2', name: '第二项目' }}
        currentUser={currentUser}
        canManage
      />,
    );

    await waitFor(() => expect(mocks.listProjectMembers).toHaveBeenLastCalledWith('project-2'));
    expect(screen.getByRole('heading', { name: '第二项目 项目成员' })).toBeInTheDocument();
  });

  it('shows an empty selection state without making member requests', () => {
    render(<ProjectMembersPanel project={null} currentUser={currentUser} canManage />);

    expect(screen.getByText('请选择或创建项目')).toBeInTheDocument();
    expect(mocks.listProjectMembers).not.toHaveBeenCalled();
    expect(mocks.listProjectMemberOptions).not.toHaveBeenCalled();
  });
});
