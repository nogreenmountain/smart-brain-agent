import * as React from 'react';
import { type LucideIcon } from 'lucide-react';

export function PageShell({
  className = '',
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex h-screen min-w-0 flex-col bg-[#eef3f9] text-[#10213e] ${className}`}>
      {children}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  icon: Icon,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  icon?: LucideIcon;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          {eyebrow && (
            <div className="flex items-center gap-2 text-xs font-bold text-brand-600">
              {Icon && <Icon size={16} aria-hidden="true" />}
              {eyebrow}
            </div>
          )}
          <h1 className={`${eyebrow ? 'mt-1' : ''} text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]`}>
            {title}
          </h1>
          {description && <p className="mt-1 text-sm leading-5 text-[#6e7d97]">{description}</p>}
        </div>
        {actions && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{actions}</div>}
      </div>
    </header>
  );
}

export function PageBody({
  className = '',
  contentClassName = '',
  children,
}: {
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <main className={`flex-1 overflow-y-auto px-4 py-6 md:px-6 ${className}`}>
      <div className={`mx-auto max-w-[1320px] ${contentClassName}`}>{children}</div>
    </main>
  );
}
