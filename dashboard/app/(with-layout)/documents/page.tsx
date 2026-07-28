'use client';

import { useEffect, useState, useRef } from 'react';
import {
  getMe,
  listProjects,
  uploadDocument,
  Project,
  MeResponse,
  UploadResult,
} from '@/lib/api/knowledge';
import { ApiError, fetchAuthenticatedApi } from '@/lib/api-client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';

interface DocumentRow {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  status: string;
  chunk_count: number;
  created_at: string;
  display_name: string;
  error_message: string | null;
}

export default function DocumentsPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>('');
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  async function loadDocs(pid: string) {
    if (!pid) return;
    try {
      const rows = await fetchAuthenticatedApi<DocumentRow[]>(
        `/v4/projects/${pid}/documents`,
      ).catch(() => [] as DocumentRow[]);
      setDocs(rows);
    } catch {
      setDocs([]);
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const [meData, projData] = await Promise.all([getMe(), listProjects()]);
        setMe(meData);
        setProjects(projData);
        if (projData.length > 0) setProjectId(projData[0].id);
      } catch (e: any) {
        if (e instanceof ApiError && e.status === 401) {
          window.location.href = '/signin';
        }
      }
    })();
  }, []);

  useEffect(() => {
    if (projectId) loadDocs(projectId);
  }, [projectId]);

  async function handleUpload() {
    const f = fileRef.current?.files?.[0];
    if (!f || !projectId) return;
    setBusy(true);
    try {
      const res: UploadResult = await uploadDocument(projectId, f, f.name);
      toast({
        title: 'Uploaded',
        description: `${res.filename}: ${res.chunk_count} chunks`,
      });
      await loadDocs(projectId);
      if (fileRef.current) fileRef.current.value = '';
    } catch (e: any) {
      toast({
        title: 'Upload failed',
        description: e?.message || 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col p-4 gap-4 max-w-6xl mx-auto w-full">
      <h1 className="text-2xl font-semibold">Documents</h1>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground w-20">Project:</span>
        <Select value={projectId} onValueChange={setProjectId}>
          <SelectTrigger className="w-96">
            <SelectValue placeholder="Select a project" />
          </SelectTrigger>
          <SelectContent>
            {projects.length === 0 && (
              <SelectItem value="__none" disabled>
                No projects available
              </SelectItem>
            )}
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name} ({p.environment})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Upload a document</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2 items-end">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.md,.txt"
            className="text-sm"
          />
          <Button onClick={handleUpload} disabled={busy || !projectId}>
            {busy ? 'Uploading…' : 'Upload'}
          </Button>
          <span className="text-xs text-muted-foreground">
            Accepted: PDF / Markdown / TXT
          </span>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documents in this project</CardTitle>
        </CardHeader>
        <CardContent>
          {docs.length === 0 ? (
            <div className="text-muted-foreground text-sm py-6 text-center">
              {projectId
                ? 'No documents yet. Upload one above.'
                : 'Select a project to see its documents.'}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b">
                  <th className="py-2">File</th>
                  <th>Status</th>
                  <th>Chunks</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className="border-b">
                    <td className="py-2">{d.display_name || d.filename}</td>
                    <td>
                      {d.status === 'ready' ? (
                        <span className="text-green-600">ready</span>
                      ) : d.status === 'failed' ? (
                        <span className="text-red-600">failed: {d.error_message}</span>
                      ) : (
                        d.status
                      )}
                    </td>
                    <td>{d.chunk_count}</td>
                    <td className="text-muted-foreground">
                      {d.created_at?.slice(0, 16)}
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
