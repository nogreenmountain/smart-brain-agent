'use client';

import { useEffect, useState } from 'react';
import {
  AuditLog,
  getMe,
  listAuditLogs,
  MeResponse,
} from '@/lib/api/knowledge';
import { ApiError } from '@/lib/api-client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';

export default function AuditAdminPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [actionFilter, setActionFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    (async () => {
      try {
        const meData = await getMe();
        setMe(meData);
        if (
          !meData.memberships.some(
            (m) => m.role === 'admin' || m.role === 'owner',
          )
        ) {
          toast({
            title: 'Access denied',
            description: 'You need admin or owner role in at least one org.',
            variant: 'destructive',
          });
        }
      } catch (e: any) {
        if (e instanceof ApiError && e.status === 401) {
          window.location.href = '/signin';
        }
      }
    })();
  }, []);

  async function reload() {
    setBusy(true);
    try {
      const filters: { user_id?: string; action?: string; limit: number } = { limit: 100 };
      if (actionFilter) filters.action = actionFilter;
      if (userFilter) filters.user_id = userFilter;
      setLogs(await listAuditLogs(filters));
    } catch (e: any) {
      toast({
        title: 'Failed to load audit logs',
        description: e?.message,
        variant: 'destructive',
      });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (me) reload();
  }, [me]);

  return (
    <div className="p-4 max-w-6xl mx-auto w-full space-y-4">
      <h1 className="text-2xl font-semibold">Audit logs</h1>
      <Card>
        <CardHeader>
          <CardTitle>Filter</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground">Action</label>
            <Input
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="search / answer / upload / login / …"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs text-muted-foreground">User ID</label>
            <Input
              value={userFilter}
              onChange={(e) => setUserFilter(e.target.value)}
              placeholder="uuid (optional)"
            />
          </div>
          <button
            onClick={reload}
            disabled={busy}
            className="px-3 py-1 rounded bg-primary text-primary-foreground text-sm"
          >
            {busy ? '…' : 'Apply'}
          </button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{logs.length} most recent</CardTitle>
        </CardHeader>
        <CardContent>
          {logs.length === 0 ? (
            <div className="text-muted-foreground text-sm py-6 text-center">
              No audit rows match.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b">
                  <th className="py-2">Time</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>Metadata</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id} className="border-b align-top">
                    <td className="py-2 font-mono">{l.created_at?.slice(0, 19)}</td>
                    <td className="font-mono">{l.user_id?.slice(0, 8) ?? '—'}</td>
                    <td>
                      <span className="px-1.5 py-0.5 rounded bg-muted text-foreground">
                        {l.action}
                      </span>
                    </td>
                    <td>
                      {l.resource_type && (
                        <div>
                          <span className="text-muted-foreground">{l.resource_type}:</span>{' '}
                          <span className="font-mono">{l.resource_id?.slice(0, 12)}</span>
                        </div>
                      )}
                    </td>
                    <td>
                      <pre className="text-[10px] whitespace-pre-wrap max-w-md">
                        {JSON.stringify(l.metadata)}
                      </pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
