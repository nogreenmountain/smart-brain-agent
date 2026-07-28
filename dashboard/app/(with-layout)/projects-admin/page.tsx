'use client';

import { useEffect, useState } from 'react';
import { getMe, listProjects, MeResponse, Project } from '@/lib/api/knowledge';
import { ApiError } from '@/lib/api-client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/components/ui/use-toast';

export default function ProjectsPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const { toast } = useToast();

  useEffect(() => {
    (async () => {
      try {
        const [meData, projData] = await Promise.all([getMe(), listProjects()]);
        setMe(meData);
        setProjects(projData);
      } catch (e: any) {
        if (e instanceof ApiError && e.status === 401) {
          window.location.href = '/signin';
          return;
        }
        toast({ title: 'Failed to load', description: e?.message, variant: 'destructive' });
      }
    })();
  }, []);

  // A user is "global admin" if they have admin or owner role in at least
  // one of their orgs (matches server-side _is_audit_admin heuristic).
  const isGlobalAdmin =
    me?.memberships.some((m) => m.role === 'admin' || m.role === 'owner') ?? false;

  if (!isGlobalAdmin) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-2">Projects</h1>
        <p className="text-muted-foreground">
          You need admin or owner role in at least one organization to manage projects.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-4xl mx-auto w-full space-y-4">
      <h1 className="text-2xl font-semibold">Projects (read-only)</h1>
      <p className="text-sm text-muted-foreground">
        Project creation and member management are not yet wired into the UI.
        Use the API endpoints directly or contact your administrator.
      </p>
      <Card>
        <CardHeader>
          <CardTitle>Projects you can see</CardTitle>
        </CardHeader>
        <CardContent>
          {projects.length === 0 ? (
            <div className="text-muted-foreground text-sm">No projects visible.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b">
                  <th className="py-2">Name</th>
                  <th>Environment</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b">
                    <td className="py-2">{p.name}</td>
                    <td>{p.environment}</td>
                    <td className="font-mono text-xs">{p.id}</td>
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
