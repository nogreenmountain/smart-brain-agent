import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProfilePage from './page';

const mocks = vi.hoisted(() => ({
  changeMyPassword: vi.fn(),
  getMe: vi.fn(),
  updateMyProfile: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    changeMyPassword: mocks.changeMyPassword,
    getMe: mocks.getMe,
    updateMyProfile: mocks.updateMyProfile,
  };
});

describe('ProfilePage', () => {
  beforeEach(() => {
    mocks.changeMyPassword.mockReset();
    mocks.getMe.mockReset();
    mocks.updateMyProfile.mockReset();
    mocks.getMe.mockResolvedValue({
      user_id: 'user-1',
      email: 'test1@local.dev',
      full_name: 'test1',
      nickname: null,
      display_name: 'test1@local.dev',
      ai_detail_visible_to_admin: false,
      memberships: [],
    });
    mocks.updateMyProfile.mockResolvedValue({
      user_id: 'user-1',
      email: 'test1@local.dev',
      full_name: 'test1',
      nickname: '研发小王',
      display_name: '研发小王',
      ai_detail_visible_to_admin: true,
      memberships: [],
    });
    mocks.changeMyPassword.mockResolvedValue({ status: 'updated' });
  });

  it('shows the email as the default member display name and saves a nickname', async () => {
    const user = userEvent.setup();
    render(<ProfilePage />);

    expect(await screen.findByRole('heading', { name: '个人中心' })).toBeInTheDocument();
    expect(screen.getByText('未设置昵称时，成员管理显示 test1@local.dev')).toBeInTheDocument();

    await user.type(screen.getByLabelText('昵称'), '研发小王');
    await user.click(screen.getByRole('checkbox', { name: '允许管理员查看详细 AI 工作记录' }));
    await user.click(screen.getByRole('button', { name: '保存个人设置' }));

    await waitFor(() => expect(mocks.updateMyProfile).toHaveBeenCalledWith('研发小王', true));
    expect(await screen.findByText('个人设置已保存')).toBeInTheDocument();
  });

  it('validates confirmation and changes the current user password', async () => {
    const user = userEvent.setup();
    render(<ProfilePage />);
    await screen.findByRole('heading', { name: '个人中心' });

    await user.type(screen.getByLabelText('当前密码'), '123456');
    await user.type(screen.getByLabelText('新密码'), '654321');
    await user.type(screen.getByLabelText('确认新密码'), '654322');
    await user.click(screen.getByRole('button', { name: '修改密码' }));

    expect(await screen.findByText('两次输入的新密码不一致')).toBeInTheDocument();
    expect(mocks.changeMyPassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText('确认新密码'));
    await user.type(screen.getByLabelText('确认新密码'), '654321');
    await user.click(screen.getByRole('button', { name: '修改密码' }));

    await waitFor(() => expect(mocks.changeMyPassword).toHaveBeenCalledWith('123456', '654321'));
    expect(await screen.findByText('密码已修改')).toBeInTheDocument();
  });
});
