'use client';

import { useEffect, useRef, useState } from 'react';
import { BrainCircuit, MessageCircleQuestion, Send } from 'lucide-react';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Textarea } from '@/components/Input';
import { PageHeader, PageShell } from '@/components/PageLayout';
import { Select } from '@/components/Select';
import {
  AnswerResult,
  Project,
  SearchHit,
  answerQuestion,
  listProjects,
} from '@/lib/api';

interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  query?: string;
  answer?: AnswerResult;
  pending?: boolean;
  error?: string;
}

export default function ChatPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listProjects()
      .then((rows) => {
        setProjects(rows);
        if (rows.length > 0) setProjectId(rows[0].id);
        else setToast('你还没有可访问的项目，请联系管理员');
      })
      .catch((error: Error) => setToast(error.message || '加载项目失败'));
  }, []);

  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [messages]);

  async function send() {
    const asked = query.trim();
    if (!asked || !projectId || busy) return;
    const timestamp = Date.now();
    const userMsg: ChatMsg = { id: `u-${timestamp}`, role: 'user', query: asked };
    const pending: ChatMsg = { id: `a-${timestamp}`, role: 'assistant', pending: true };
    setMessages((current) => [...current, userMsg, pending]);
    setQuery('');
    setBusy(true);
    try {
      const answer = await answerQuestion(projectId, asked, 5);
      setMessages((current) =>
        current.map((item) => (item.id === pending.id ? { ...item, pending: false, answer } : item)),
      );
    } catch (error: any) {
      setMessages((current) =>
        current.map((item) =>
          item.id === pending.id
            ? { ...item, pending: false, error: error?.message || '请求失败' }
            : item,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="PROJECT ASSISTANT"
        icon={MessageCircleQuestion}
        title="知识问答"
        description="基于项目知识库和长期记忆回答问题，并保留引用来源。"
        actions={
          <div className="w-full sm:w-72">
            <Select
              value={projectId}
              onChange={(value) => {
                setProjectId(value);
                setMessages([]);
              }}
              placeholder={projects.length === 0 ? '暂无可访问项目' : '选择项目'}
              options={projects.map((project) => ({
                value: project.id,
                label: project.name,
              }))}
              disabled={projects.length === 0}
            />
          </div>
        }
      />

      <div ref={scrollerRef} className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
        <div className="mx-auto max-w-[920px]">
          {messages.length === 0 && (
            <EmptyState
              title="问一个和项目有关的问题"
              hint="智慧大脑会从原始资料和已经确认的长期记忆中寻找答案。"
            />
          )}
          <div className="space-y-5">
            {messages.map((message) =>
              message.role === 'user' ? (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-[86%] rounded-lg bg-brand-600 px-4 py-3 text-sm leading-6 text-white shadow-sm sm:max-w-[75%]">
                    {message.query}
                  </div>
                </div>
              ) : (
                <div key={message.id} className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                    <BrainCircuit size={17} aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    {message.pending ? (
                      <Card className="bg-[#f7f9fc] px-4 py-3 text-sm text-[#6e7d97]">
                        <LoadingDots /> <span className="ml-2">正在整理答案</span>
                      </Card>
                    ) : message.error ? (
                      <Card className="border-[#efc3c8] bg-[#fff5f6] px-4 py-3 text-sm text-[#b83d49]">
                        {message.error}
                      </Card>
                    ) : message.answer ? (
                      <Card>
                        <div className="whitespace-pre-wrap px-5 py-4 text-sm leading-7 text-[#253655]">
                          {message.answer.synthesis}
                        </div>
                        {message.answer.source === 'stub' && (
                          <div className="px-5 pb-3 text-xs text-[#9a5a0d]">
                            大模型暂时不可用，当前显示检索到的资料摘要。
                          </div>
                        )}
                        {message.answer.hits.length > 0 && (
                          <details className="border-t border-[#e5ebf3] px-5 py-3 text-xs">
                            <summary className="cursor-pointer font-medium text-[#53647d] hover:text-[#10213e]">
                              {message.answer.hits.length} 个引用片段
                            </summary>
                            <div className="mt-3 space-y-2">
                              {message.answer.hits.map((hit, index) => (
                                <SourceItem key={hit.chunk_id} idx={index + 1} hit={hit} />
                              ))}
                            </div>
                          </details>
                        )}
                      </Card>
                    ) : null}
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      </div>

      <form
        className="border-t border-[#d7e0ec] bg-white px-4 py-4 md:px-6"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <div className="mx-auto flex max-w-[920px] flex-col items-stretch gap-3 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1">
            <label htmlFor="chat-question" className="sr-only">输入问题</label>
            <Textarea
              id="chat-question"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入你的问题，Ctrl+Enter 快速发送"
              rows={2}
              className="min-h-[72px]"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void send();
                }
              }}
              disabled={!projectId || busy}
            />
          </div>
          <Button type="submit" className="w-full sm:w-auto" disabled={busy || !projectId || !query.trim()}>
            <Send size={16} aria-hidden="true" />
            {busy ? '回答中' : '发送'}
          </Button>
        </div>
      </form>

      {toast && <Toast message={toast} kind="error" />}
    </PageShell>
  );
}

function SourceItem({ idx, hit }: { idx: number; hit: SearchHit }) {
  const location = hit.source_page
    ? `第 ${hit.source_page} 页`
    : hit.source_line
      ? `第 ${hit.source_line} 行`
      : '';
  return (
    <div className="rounded-md border border-[#d7e0ec] bg-[#f7f9fc] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[#53647d]">
        <span className="min-w-0 break-words">
          <span className="font-mono text-[#8b99ae]">[{idx}]</span> {hit.document_name}
          {location && <span className="ml-1 text-[#8b99ae]">{location}</span>}
        </span>
        <span className="shrink-0 text-[10px] text-[#8b99ae]">
          相关度 {(hit.score * 100).toFixed(1)}%
        </span>
      </div>
      <div className="mt-1 line-clamp-3 leading-5 text-[#253655]">{hit.content}</div>
    </div>
  );
}
