'use client';

import { useEffect, useState } from 'react';
import {
  answerQuestion,
  getMe,
  listProjects,
  searchKnowledge,
  SearchHit,
  Project,
  MeResponse,
} from '@/lib/api/knowledge';
import { fetchAuthenticatedApi, ApiError } from '@/lib/api-client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  query?: string;
  synthesis?: string;
  source?: 'llm' | 'stub';
  hits?: SearchHit[];
  pending?: boolean;
}

export default function ChatPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>('');
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

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
          return;
        }
        toast({
          title: 'Failed to load',
          description: e?.message || 'Unknown error',
          variant: 'destructive',
        });
      }
    })();
  }, []);

  async function handleAsk() {
    if (!query.trim() || !projectId || busy) return;
    const userMsg: Message = { id: `u-${Date.now()}`, role: 'user', query };
    const pendingMsg: Message = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      pending: true,
    };
    setMessages((m) => [...m, userMsg, pendingMsg]);
    setQuery('');
    setBusy(true);
    try {
      const res = await answerQuestion(projectId, userMsg.query || '', 5);
      setMessages((m) =>
        m.map((x) =>
          x.id === pendingMsg.id
            ? {
                ...x,
                pending: false,
                synthesis: res.synthesis,
                source: res.source,
                hits: res.hits,
              }
            : x,
        ),
      );
    } catch (e: any) {
      setMessages((m) => m.filter((x) => x.id !== pendingMsg.id));
      toast({
        title: 'Query failed',
        description: e?.message || 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch() {
    if (!query.trim() || !projectId || busy) return;
    setBusy(true);
    try {
      const res = await searchKnowledge(projectId, query, 5);
      toast({
        title: `Found ${res.hits.length} chunks`,
        description: res.hits.map((h) => h.document_name).join(', ').slice(0, 200),
      });
    } catch (e: any) {
      toast({ title: 'Search failed', description: e?.message, variant: 'destructive' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-4 max-w-5xl mx-auto w-full">
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-semibold">Chat</h1>
        {me && (
          <span className="text-sm text-muted-foreground">
            {me.email} · {me.memberships.length} org(s)
          </span>
        )}
      </div>

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

      <Card className="flex-1 overflow-y-auto">
        <CardContent className="p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground py-12">
              Ask a question about your project documents.
            </div>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={
                m.role === 'user'
                  ? 'flex justify-end'
                  : 'flex justify-start'
              }
            >
              <div
                className={
                  m.role === 'user'
                    ? 'max-w-[80%] rounded-lg bg-primary text-primary-foreground px-4 py-2'
                    : 'max-w-[85%] w-full'
                }
              >
                {m.role === 'user' ? (
                  <div className="whitespace-pre-wrap">{m.query}</div>
                ) : (
                  <div className="space-y-3">
                    {m.pending ? (
                      <div className="text-muted-foreground italic">thinking…</div>
                    ) : (
                      <>
                        <div className="whitespace-pre-wrap text-sm">
                          {m.synthesis}
                        </div>
                        {m.source === 'llm' && (
                          <div className="text-xs text-muted-foreground">
                            via LLM
                          </div>
                        )}
                        {m.source === 'stub' && (
                          <div className="text-xs text-amber-600">
                            (LLM unavailable, retrieval-only)
                          </div>
                        )}
                        {m.hits && m.hits.length > 0 && (
                          <details className="text-xs">
                            <summary className="cursor-pointer text-muted-foreground">
                              {m.hits.length} source chunk(s)
                            </summary>
                            <div className="mt-2 space-y-2">
                              {m.hits.map((h, i) => (
                                <div
                                  key={h.chunk_id}
                                  className="border-l-2 border-muted pl-2 py-1"
                                >
                                  <div className="text-muted-foreground">
                                    [{i + 1}] {h.document_name}
                                    {h.source_page
                                      ? ` p.${h.source_page}`
                                      : h.source_line
                                        ? ` L${h.source_line}`
                                        : ''}{' '}
                                    · score {h.score.toFixed(3)}
                                  </div>
                                  <div className="text-foreground/80 mt-1 line-clamp-4">
                                    {h.content}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </details>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex gap-2 items-end">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a question about the project's documents…"
          className="flex-1"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleAsk();
            }
          }}
        />
        <div className="flex flex-col gap-2">
          <Button onClick={handleAsk} disabled={busy || !projectId}>
            {busy ? '...' : 'Ask'}
          </Button>
          <Button onClick={handleSearch} variant="outline" disabled={busy || !projectId}>
            Search
          </Button>
        </div>
      </div>
    </div>
  );
}
