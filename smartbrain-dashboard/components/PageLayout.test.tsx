import { render, screen } from '@testing-library/react';
import { BookOpenText } from 'lucide-react';
import { describe, expect, it } from 'vitest';

import { Button } from './Button';
import { PageBody, PageHeader, PageShell } from './PageLayout';

describe('shared page layout', () => {
  it('renders the standard title, responsive actions, and content width', () => {
    render(
      <PageShell>
        <PageHeader
          eyebrow="LONG-TERM MEMORY"
          icon={BookOpenText}
          title="项目 Wiki"
          description="项目中已经确认的长期知识。"
          actions={<Button>刷新</Button>}
        />
        <PageBody>页面内容</PageBody>
      </PageShell>,
    );

    expect(screen.getByRole('heading', { name: '项目 Wiki' })).toHaveClass('text-[26px]');
    expect(screen.getByText('LONG-TERM MEMORY').closest('header')?.firstElementChild).toHaveClass('max-w-[1320px]');
    expect(screen.getByText('页面内容')).toHaveClass('max-w-[1320px]');
    expect(screen.getByRole('button', { name: '刷新' }).parentElement).toHaveClass('sm:w-auto');
  });

  it('keeps normal controls at 40px and small controls at 32px', () => {
    render(
      <>
        <Button>普通按钮</Button>
        <Button size="sm">小按钮</Button>
      </>,
    );

    expect(screen.getByRole('button', { name: '普通按钮' })).toHaveClass('h-10');
    expect(screen.getByRole('button', { name: '小按钮' })).toHaveClass('h-8');
  });
});
