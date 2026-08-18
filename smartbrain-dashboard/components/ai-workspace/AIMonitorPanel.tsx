'use client';

import { useState } from 'react';
import { MonitorCheck, TimerReset } from 'lucide-react';

import MonitorSetupPage from '@/app/(with-shell)/monitor/setup/legacy-page';
import { SharedDeviceSessionPanel } from './SharedDeviceSessionPanel';

export default function AIMonitorPanel() {
  const [view, setView] = useState<'personal' | 'temporary'>('personal');

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-[#d7e0ec] bg-white px-4 py-3 md:px-6">
        <div
          role="tablist"
          aria-label="AI Monitor 类型"
          className="mx-auto grid max-w-[1320px] grid-cols-2 gap-2 rounded-xl bg-[#f2f6fb] p-1 sm:w-fit sm:min-w-[440px]"
        >
          <button
            type="button"
            role="tab"
            aria-selected={view === 'personal'}
            onClick={() => setView('personal')}
            className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition ${view === 'personal' ? 'bg-white text-[#10213e] shadow-sm' : 'text-[#6e7d97] hover:text-[#253655]'}`}
          >
            <MonitorCheck size={17} aria-hidden="true" />
            个人 AI Monitor
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'temporary'}
            onClick={() => setView('temporary')}
            className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition ${view === 'temporary' ? 'bg-white text-[#10213e] shadow-sm' : 'text-[#6e7d97] hover:text-[#253655]'}`}
          >
            <TimerReset size={17} aria-hidden="true" />
            临时 Token Monitor
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {view === 'personal' ? (
          <MonitorSetupPage embedded />
        ) : (
          <div className="h-full overflow-y-auto px-4 py-6 md:px-6">
            <div className="mx-auto max-w-[1320px]">
              <SharedDeviceSessionPanel />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
