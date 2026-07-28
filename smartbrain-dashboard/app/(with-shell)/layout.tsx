'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getMe, Me, ApiError } from '@/lib/api';
import { Shell } from '@/components/Shell';

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const m = await getMe();
        if (!cancelled) {
          setMe(m);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          if (e instanceof ApiError && e.status === 401) {
            router.replace('/login');
            return;
          }
          router.replace('/login');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (loading || !me) {
    return (
      <div className="flex h-screen items-center justify-center text-gray-400">
        <span className="text-sm">加载中…</span>
      </div>
    );
  }

  return <Shell me={me}>{children}</Shell>;
}