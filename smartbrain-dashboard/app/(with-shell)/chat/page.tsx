'use client';

import { useEffect, useRef, useState } from 'react';
import {
  answerQuestion,
  listProjects,
  Project,
  SearchHit,
  AnswerResult,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { Textarea } from '@/components/Input';
import { Select } from '@/components/Select';
import { Card } from '@/components/Card';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';

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
    (async () => {
      try {
        const ps = await listProjects();
        setProjects(ps);
        if (ps.length > 0) setProjectId(ps[0].id);
        else setToast('你还没有可访问的项目，请联系管理员');
      } catch (e: any) {
        setToast(e?.message || '加载项目失败');
      }
    })();
  }, []);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages]);

  async function send() {
    if (!query.trim() || !projectId || busy) return;
    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: 'user', query };
    const pending: ChatMsg = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      pending: true,
    };
    setMessages((m) => [...m, userMsg, pending]);
    const asked = query;
    setQuery('');
    setBusy(true);
    try {
      const ans = await answerQuestion(projectId, asked, 5);
      setMessages((m) =>
        m.map((x) => (x.id === pending.id ? { ...x, pending: false, answer: ans } : x)),
      );
    } catch (e: any) {
      setMessages((m) =>
        m.map((x) => (x.id === pending.id ? { ...x, pending: false, error: e?.message || '请求失败' } : x)),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-screen">
      {/* 顶栏 */}
      <header className="px-6 py-3 border-b border-gray-200 bg-white flex items-center gap-4">
        <div className="text-lg font-semibold text-gray-900">问答</div>
        <div className="flex-1" />
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500">项目</span>
          <div className="w-72">
            <Select
              value={projectId}
              onChange={setProjectId}
              placeholder={projects.length === 0 ? '暂无可访问项目' : '选择项目'}
              options={projects.map((p) => ({
                value: p.id,
                label: `${p.name} (${p.environment})`,
              }))}
              disabled={projects.length === 0}
            />
          </div>
        </div>
      </header>

      {/* 对话区 */}
      <div ref={scrollerRef} className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <EmptyState
            icon="💭"
            title="提出一个问题试试"
            hint="智慧大脑会从项目知识库里找答案,并标注来源"
          />
        )}
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[80%] bg-brand-600 text-white rounded-2xl rounded-tr-md px-4 py-2.5 text-sm whitespace-pre-wrap">
                  {m.query}
                </div>
              </div>
            ) : (
              <div key={m.id} className="flex justify-start">
                <div className="max-w-[90%] w-full">
                  <div className="text-xs text-gray-500 mb-1.5">🧠 智慧大脑</div>
                  {m.pending ? (
                    <Card className="bg-gray-50">
                      <div className="px-4 py-3 text-sm text-gray-500">
                        <LoadingDots /> 正在思考...
                      </div>
                    </Card>
                  ) : m.error ? (
                    <Card className="border-red-200 bg-red-50">
                      <div className="px-4 py-3 text-sm text-red-700">{m.error}</div>
                    </Card>
                  ) : m.answer ? (
                    <Card>
                      <div className="px-5 py-4 prose-sm text-sm text-gray-900 whitespace-pre-wrap">
                        {m.answer.synthesis}
                      </div>
                      {m.answer.source === 'stub' && (
                        <div className="px-5 pb-3 text-xs text-amber-600">
                          ⚠ LLM 暂不可用,展示的是检索结果片段
                        </div>
                      )}
                      {m.answer.hits.length > 0 && (
                        <details className="border-t border-gray-100 px-5 py-3 text-xs">
                          <summary className="cursor-pointer text-gray-600 hover:text-gray-900">
                            📎 {m.answer.hits.length} 个引用片段
                          </summary>
                          <div className="mt-3 space-y-2">
                            {m.answer.hits.map((h, i) => (
                              <SourceItem key={h.chunk_id} idx={i + 1} hit={h} />
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

      {/* 输入区 */}
      <div className="border-t border-gray-200 bg-white px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-3 items-end">
            <Textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入你的问题, Ctrl+Enter 发送"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  send();
                }
              }}
              disabled={!projectId}
            />
            <Button onClick={send} disabled={busy || !projectId || !query.trim()}>
              {busy ? <LoadingDots /> : '发送'}
            </Button>
          </div>
          <div className="text-xs text-gray-400 mt-1.5">
            {projectId ? '按 Ctrl+Enter 快速发送' : '请先在右上角选择项目'}
          </div>
        </div>
      </div>

      {toast && <Toast message={toast} kind="error" />}
    </div>
  );
}

function SourceItem({ idx, hit }: { idx: number; hit: SearchHit }) {
  const loc = hit.source_page
    ? `第 ${hit.source_page} 页`
    : hit.source_line
      ? `第 ${hit.source_line} 行`
      : '';
  return (
    <div className="bg-gray-50 border border-gray-100 rounded p-2.5">
      <div className="flex items-center justify-between text-gray-600">
        <span>
          <span className="font-mono text-gray-400">[{idx}]</span> {hit.document_name}
          {loc && <span className="text-gray-400 ml-1">{loc}</span>}
        </span>
        <span className="text-gray-400 text-[10px]">相关度 {(hit.score * 100).toFixed(1)}%</span>
      </div>
      <div className="mt-1 text-gray-700 line-clamp-3">{hit.content}</div>
    </div>
  );
}