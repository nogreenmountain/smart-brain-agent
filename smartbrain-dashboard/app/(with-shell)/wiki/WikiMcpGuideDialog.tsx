'use client';

import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Download,
  KeyRound,
  MonitorUp,
  PlugZap,
  ShieldCheck,
  TerminalSquare,
  X,
} from 'lucide-react';
import { Button } from '@/components/Button';

const DISMISSED_STORAGE_KEY = 'smartbrain:wiki-mcp-guide:dismissed';

const STEPS = [
  {
    icon: TerminalSquare,
    title: '确认已安装 Codex CLI',
    description: '先确认本机已安装 Codex CLI，并且 codex.cmd 或 codex.exe 已加入系统 PATH。',
    detail: '可以在终端运行 codex.cmd --version 检查。',
  },
  {
    icon: KeyRound,
    title: '创建个人 MCP Token',
    description: '填写 Token 名称和有效期，并选择是否允许提交待审批记忆。',
    detail: '只读 Token 只能查询；勾选后可提交提案，但仍需管理员审批才会进入正式 Wiki。',
  },
  {
    icon: Download,
    title: '安装到 Codex CLI',
    description: '创建 Token 后，点击“安装到 Codex CLI”，运行下载的 CMD 安装器。',
    detail: '安装器会保存当前 Token、安装 Company Memory 插件并配置智慧大脑 MCP。',
  },
  {
    icon: MonitorUp,
    title: '同步到 ChatGPT 桌面端',
    description: '安装成功后，完全退出并重新启动 ChatGPT 桌面端，然后新建一个 Codex 任务。',
    detail: '插件用于桌面端的 Codex 模式；普通 ChatGPT 对话目前不会读取这套本地 MCP 配置。',
  },
] as const;

export function WikiMcpGuideDialog() {
  const [open, setOpen] = useState(false);
  const [doNotShowAgain, setDoNotShowAgain] = useState(false);

  useEffect(() => {
    setOpen(window.localStorage.getItem(DISMISSED_STORAGE_KEY) !== '1');
  }, []);

  function closeGuide() {
    if (doNotShowAgain) {
      window.localStorage.setItem(DISMISSED_STORAGE_KEY, '1');
    }
    setOpen(false);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-3 backdrop-blur-[2px] sm:p-6">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="wiki-mcp-guide-title"
        className="max-h-[calc(100vh-1.5rem)] w-full max-w-3xl overflow-y-auto rounded-xl border border-white/70 bg-white shadow-[0_28px_80px_rgba(15,35,66,0.32)] sm:max-h-[calc(100vh-3rem)]"
      >
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur sm:px-6">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
            <PlugZap size={20} aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold tracking-wide text-brand-600">首次使用指引</div>
            <h2 id="wiki-mcp-guide-title" className="mt-1 text-xl font-semibold text-[#10213e] sm:text-2xl">
              智慧大脑 MCP 使用指引
            </h2>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
              按以下步骤把 Company Memory 插件安装到 Codex，并在 ChatGPT 桌面端的 Codex 模式中使用。
            </p>
          </div>
          <button
            type="button"
            aria-label="关闭智慧大脑 MCP 使用指引"
            title="关闭"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6e7d97] transition-colors hover:bg-[#f1f4f8] hover:text-[#10213e]"
            onClick={closeGuide}
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>

        <div className="px-4 py-5 sm:px-6">
          <div className="rounded-lg border border-brand-500/20 bg-brand-500/[0.06] px-4 py-3 text-sm leading-6 text-[#253655]">
            <div className="flex items-start gap-2">
              <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-brand-600" aria-hidden="true" />
              <p>
                <span className="font-semibold">安装方式：</span>
                网页安装器通过 Codex CLI 完成安装；安装后可供 Codex CLI 和 ChatGPT 桌面端的 Codex 模式共同使用。
              </p>
            </div>
          </div>

          <ol className="mt-5 grid gap-3 sm:grid-cols-2">
            {STEPS.map((step, index) => {
              const Icon = step.icon;
              return (
                <li key={step.title} className="rounded-lg border border-[#d7e0ec] bg-[#fbfcfe] p-4">
                  <div className="flex items-start gap-3">
                    <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm ring-1 ring-[#d7e0ec]">
                      <Icon size={18} aria-hidden="true" />
                      <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-500 px-1 text-[10px] font-bold text-white">
                        {index + 1}
                      </span>
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-[#10213e]">{step.title}</h3>
                      <p className="mt-1 text-sm leading-6 text-[#253655]">{step.description}</p>
                      <p className="mt-1 text-xs leading-5 text-[#6e7d97]">{step.detail}</p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-4 flex items-start gap-2 rounded-lg border border-[#f0a23a]/30 bg-[#fff8ed] px-4 py-3 text-xs leading-5 text-[#7b4a12]">
            <ShieldCheck size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>Token 和下载的 CMD 安装器都代表你的个人身份，请勿转发给其他员工。每位员工都应登录自己的智慧大脑账号完成安装。</p>
          </div>
        </div>

        <div className="sticky bottom-0 flex flex-col gap-3 border-t border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm text-[#253655]">
            <input
              type="checkbox"
              checked={doNotShowAgain}
              onChange={(event) => setDoNotShowAgain(event.target.checked)}
              className="h-4 w-4 rounded border-[#b8c6da] text-brand-600 focus:ring-brand-500"
            />
            下次不再提示
          </label>
          <Button type="button" className="w-full sm:w-auto" onClick={closeGuide}>
            我知道了
          </Button>
        </div>
      </section>
    </div>
  );
}
