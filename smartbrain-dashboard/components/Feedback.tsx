'use client';

export function LoadingDots() {
  return (
    <span className="inline-flex gap-1">
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  );
}

export function EmptyState({ icon = '📭', title, hint }: { icon?: string; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-gray-400">
      <div className="text-5xl mb-3">{icon}</div>
      <div className="text-sm">{title}</div>
      {hint && <div className="text-xs mt-1 text-gray-400">{hint}</div>}
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
      className={`fixed bottom-6 right-6 px-4 py-3 rounded-md shadow-lg text-sm text-white ${
        kind === 'error' ? 'bg-red-600' : 'bg-gray-900'
      }`}
    >
      {message}
    </div>
  );
}