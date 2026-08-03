'use client';

import { Inbox } from 'lucide-react';

export function LoadingDots() {
  return (
    <span className="inline-flex gap-1">
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  );
}

export function EmptyState({ icon, title, hint }: { icon?: string; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-[#8b99ae]">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-[#d7e0ec] bg-white text-[#6e7d97]">
        {icon ? <span className="text-lg" aria-hidden="true">{icon}</span> : <Inbox size={19} aria-hidden="true" />}
      </div>
      <div className="text-sm font-medium text-[#6e7d97]">{title}</div>
      {hint && <div className="mt-1 text-center text-xs text-[#8b99ae]">{hint}</div>}
    </div>
  );
}

export function Toast({
  message,
  kind = 'info',
}: {
  message: string;
  kind?: 'info' | 'error';
}) {
  return (
    <div
      role="status"
      className={`fixed bottom-5 left-4 right-4 z-50 rounded-lg px-4 py-3 text-sm text-white shadow-lg sm:bottom-6 sm:left-auto sm:right-6 sm:max-w-md ${
        kind === 'error' ? 'bg-[#b83d49]' : 'bg-[#10213e]'
      }`}
    >
      {message}
    </div>
  );
}
