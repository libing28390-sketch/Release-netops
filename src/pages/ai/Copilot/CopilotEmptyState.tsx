import React from 'react';
import { Sparkles, MapPin, Sliders, AlertTriangle, BookOpen, ArrowRight } from 'lucide-react';

interface CopilotEmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

export const CopilotEmptyState: React.FC<CopilotEmptyStateProps> = ({ onSelectPrompt }) => {
  // One icon per card: the titles used to start with an emoji as well, so
  // each card showed two icons side by side.
  const cards = [
    {
      icon: <MapPin className="w-4 h-4 text-emerald-500" />,
      title: 'IP / MAC 定位',
      desc: '根据 IP 查交换机、端口与 VLAN',
      prompt: '192.168.10.20 在哪台交换机哪个端口？',
    },
    {
      icon: <Sliders className="w-4 h-4 text-indigo-500" />,
      title: '生成设备配置',
      desc: '支持 Huawei, Cisco, H3C 命令生成',
      prompt: '生成一份华为 S6800 OSPF Area 0 配置命令',
    },
    {
      icon: <AlertTriangle className="w-4 h-4 text-amber-500" />,
      title: '故障排查分析',
      desc: '诊断接口 Down、邻居异常与高 CPU',
      prompt: '交换机 OSPF 邻居长期处于 ExStart 状态怎么排查？',
    },
    {
      icon: <BookOpen className="w-4 h-4 text-blue-500" />,
      title: '本地 RAG 知识库',
      desc: '检索内部网络 SOP 与标准规范',
      prompt: '查找本地知识库中关于网络变更及巡检的标准 SOP',
    },
  ];

  return (
    <div className="flex min-h-[260px] flex-1 flex-col items-center justify-center max-w-3xl mx-auto w-full px-4 text-center select-none space-y-7 py-10">
      {/* Gemini-style Gradient Greeting */}
      <div className="space-y-2.5">
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-500 text-white shadow-md shadow-indigo-500/20">
          <Sparkles className="w-5 h-5" />
        </div>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight bg-gradient-to-r from-blue-600 via-indigo-500 to-purple-500 bg-clip-text text-transparent">
          你好，有什么我可以帮你的？
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Nexora AI · 查资产、定位端口、生成厂商配置与排查网络故障
        </p>
      </div>

      {/* Gemini-style Lightweight Suggestion Chips */}
      <div className="flex flex-wrap items-center justify-center gap-2.5 max-w-2xl">
        {cards.map((c, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onSelectPrompt(c.prompt)}
            className="inline-flex items-center gap-2 rounded-full border border-gray-200/80 dark:border-gray-700/80 bg-white dark:bg-gray-800/70 px-4 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 shadow-2xs transition hover:border-indigo-300 hover:bg-indigo-50/40 dark:hover:border-indigo-700 dark:hover:bg-gray-800 cursor-pointer"
          >
            {c.icon}
            <span>{c.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
