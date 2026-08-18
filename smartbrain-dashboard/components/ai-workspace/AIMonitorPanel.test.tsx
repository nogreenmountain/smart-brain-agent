import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import AIMonitorPanel from './AIMonitorPanel';

vi.mock('@/app/(with-shell)/monitor/setup/legacy-page', () => ({
  default: () => <div>个人版完整内容</div>,
}));

vi.mock('./SharedDeviceSessionPanel', () => ({
  SharedDeviceSessionPanel: () => <div>临时版完整内容</div>,
}));

describe('AIMonitorPanel', () => {
  it('keeps personal and temporary monitors as two top-controlled pages', async () => {
    const user = userEvent.setup();
    render(<AIMonitorPanel />);

    const personal = screen.getByRole('tab', { name: '个人 AI Monitor' });
    const temporary = screen.getByRole('tab', { name: '临时 Token Monitor' });
    expect(personal).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('个人版完整内容')).toBeInTheDocument();
    expect(screen.queryByText('临时版完整内容')).not.toBeInTheDocument();

    await user.click(temporary);

    expect(temporary).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('临时版完整内容')).toBeInTheDocument();
    expect(screen.queryByText('个人版完整内容')).not.toBeInTheDocument();
  });
});
