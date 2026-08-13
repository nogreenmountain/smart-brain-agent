import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AIWorkspacePage } from './AIWorkspacePage';

vi.mock('./AIRecordsPanel', () => ({ default: () => <div>records panel</div> }));
vi.mock('./AILeaderboardPanel', () => ({ default: () => <div>leaderboard panel</div> }));
vi.mock('./AIWorklogsPanel', () => ({ default: () => <div>logs panel</div> }));
vi.mock('./AIMonitorPanel', () => ({ default: () => <div>monitor panel</div> }));

describe('AIWorkspacePage', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/workday');
  });

  it('renders one lazy workspace view at a time and keeps the selected view in the URL', async () => {
    const user = userEvent.setup();
    render(<AIWorkspacePage initialView="records" />);

    expect(screen.getByRole('heading', { name: 'AI 工作台' })).toBeInTheDocument();
    expect(await screen.findByText('records panel')).toBeInTheDocument();
    expect(screen.queryByText('leaderboard panel')).not.toBeInTheDocument();

    const leaderboard = screen.getByRole('tab', { name: '团队排行' });
    await user.click(leaderboard);

    expect(await screen.findByText('leaderboard panel')).toBeInTheDocument();
    expect(screen.queryByText('records panel')).not.toBeInTheDocument();
    expect(leaderboard).toHaveAttribute('aria-selected', 'true');
    expect(window.location.pathname + window.location.search).toBe('/workday?view=leaderboard');
  });

  it('honours the initial view used by a legacy route', async () => {
    render(<AIWorkspacePage initialView="monitor" />);

    expect(await screen.findByText('monitor panel')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '设备与同步' })).toHaveAttribute('aria-selected', 'true');
  });
});
