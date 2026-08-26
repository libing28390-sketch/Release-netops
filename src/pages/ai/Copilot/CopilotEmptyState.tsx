import React from 'react';
import { Sparkles, MapPin, Sliders, AlertTriangle, BookOpen, ArrowRight } from 'lucide-react';

interface CopilotEmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

export const CopilotEmptyState: React.FC<CopilotEmptyStateProps> = ({ onSelectPrompt }) => {
  const cards = [
    {
      icon: <MapPin className="w-4 h-4 text-emerald-500" />,
      title: '🔍 IP / MAC 定位',
      desc: '根据 IP 查交换机、端口与 VLAN',
      prompt: '192.168.10.20 在哪台交换机哪个端口？',
    },
    {
      icon: <Sliders className="w-4 h-4 text-indigo-500" />,
      title: '⚙ 生成设备配置',
      desc: '支持 Huawei, Cisco, H3C 命令生成',
      prompt: '生成一份华为 S6800 OSPF Area 0 配置命令',
    },
    {
      icon: <AlertTriangle className="w-4 h-4 text-amber-500" />,
      title: '📊 故障排查分析',
      desc: '诊断接口 Down、邻居异常与高 CPU',
      prompt: '交换机 OSPF 邻居长期处于 ExStart 状态怎么排查？',
    },
    {
      icon: <BookOpen className="w-4 h-4 text-blue-500" />,
      title: '📚 本地 RAG 知识库',
      desc: '检索内部网络 SOP 与标准规范',
      prompt: '查找本地知识库中关于网络变更及巡检的标准 SOP',
    },
  ];

  return (
    <div className="flex min-h-[220px] flex-1 flex-col items-center justify-center max-w-2xl mx-auto w-full px-4 text-center select-none space-y-6 sm:space-y-8 py-6 sm:py-10">
      {/* Hero Icon & Greeting */}
      <div className="space-y-3">
        <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-100 dark:border-indigo-900 flex items-center justify-center text-indigo-600 dark:text-indigo-400 mx-auto shadow-sm">
          <Sparkles className="w-6 h-6" />
        </div>
        <h1 className="nx-page-title text-gray-900 dark:text-white">
          Nexora AI
        </h1>
        <p className="nx-page-description max-w-md mx-auto text-gray-500 dark:text-gray-400">
          网络运维 Copilot，有问题直接问我。支持查资产、定位端口、生成厂商配置与排查故障。
        </p>
      </div>

      {/* Quick Start Feature Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 w-full text-left">
        {cards.map((c, idx) => (
          <button
            key={idx}
            onClick={() => onSelectPrompt(c.prompt)}
            className="p-3.5 bg-gray-50/70 dark:bg-gray-800/40 hover:bg-gray-100 dark:hover:bg-gray-800 border border-gray-200/70 dark:border-gray-700/60 rounded-2xl transition group text-left flex flex-col justify-between space-y-2 cursor-pointer"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {c.icon}
                <span className="font-semibold text-gray-900 dark:text-white text-xs">{c.title}</span>
              </div>
              <ArrowRight className="w-3.5 h-3.5 text-gray-400 group-hover:text-indigo-500 group-hover:translate-x-0.5 transition" />
            </div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 leading-normal">
              {c.desc}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
};
