export interface ExportableCitation {
  title?: string;
  source?: string;
  url?: string;
  snippet?: string;
  source_type?: string;
}

export interface ExportableMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  created_at?: string;
  route_model?: string;
  provider_id?: string;
  input_tokens?: number;
  output_tokens?: number;
  cached_tokens?: number;
  sources?: ExportableCitation[];
}

export interface ExportableConversation {
  id: string;
  title: string;
  modelName?: string;
  exportedAt?: Date;
  messages: ExportableMessage[];
}

const pad2 = (n: number) => String(n).padStart(2, '0');

export function buildExportFilename(title: string, ext: 'md' | 'json', now: Date = new Date()): string {
  const safeTitle = (title || '新对话')
    .trim()
    .replace(/[\\/:*?"<>|\r\n]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 48) || '新对话';
  const stamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}_${pad2(now.getHours())}${pad2(now.getMinutes())}`;
  return `Nexora_${safeTitle}_${stamp}.${ext}`;
}

export function formatConversationAsMarkdown(conv: ExportableConversation): string {
  const exportedAt = conv.exportedAt || new Date();
  const lines: string[] = [
    `# ${conv.title || '新对话'}`,
    '',
    `- **导出时间**：${exportedAt.toLocaleString('zh-CN', { hour12: false })}`,
    `- **会话 ID**：\`${conv.id}\``,
  ];
  if (conv.modelName) {
    lines.push(`- **当前模型**：${conv.modelName}`);
  }
  lines.push(`- **消息条数**：${conv.messages.length}`);
  lines.push('', '---', '');

  conv.messages.forEach((msg, index) => {
    const roleLabel = msg.role === 'user' ? '用户' : 'Nexora AI';
    const timeStr = msg.created_at ? ` · ${msg.created_at}` : '';
    lines.push(`## ${index + 1}. ${roleLabel}${timeStr}`, '');
    lines.push((msg.content || '').trim() || '（空内容）', '');

    if (msg.role === 'assistant') {
      const hasTokens =
        typeof msg.input_tokens === 'number' ||
        typeof msg.output_tokens === 'number' ||
        typeof msg.cached_tokens === 'number';
      if (hasTokens) {
        lines.push(
          `> Token 统计：输入 ${msg.input_tokens ?? 0} · 输出 ${msg.output_tokens ?? 0} · 缓存 ${msg.cached_tokens ?? 0}`,
          '',
        );
      }
      if (Array.isArray(msg.sources) && msg.sources.length > 0) {
        lines.push('**参考来源：**');
        msg.sources.forEach((src, sIdx) => {
          const label = src.title || src.source || `来源 ${sIdx + 1}`;
          if (src.url) {
            lines.push(`- [${label}](${src.url})`);
          } else {
            lines.push(`- ${label}`);
          }
        });
        lines.push('');
      }
    }
  });

  return lines.join('\n').trimEnd() + '\n';
}

export function formatConversationAsJson(conv: ExportableConversation): string {
  const exportedAt = conv.exportedAt || new Date();
  const payload = {
    schema_version: '1.0',
    exported_at: exportedAt.toISOString(),
    conversation: {
      id: conv.id,
      title: conv.title || '新对话',
      model: conv.modelName || null,
      message_count: conv.messages.length,
    },
    messages: conv.messages.map((msg) => ({
      id: msg.id,
      role: msg.role,
      content: msg.content,
      created_at: msg.created_at || null,
      model: msg.route_model || null,
      provider_id: msg.provider_id || null,
      tokens:
        typeof msg.input_tokens === 'number' ||
        typeof msg.output_tokens === 'number' ||
        typeof msg.cached_tokens === 'number'
          ? {
              input: msg.input_tokens ?? 0,
              output: msg.output_tokens ?? 0,
              cached: msg.cached_tokens ?? 0,
            }
          : null,
      sources: msg.sources || [],
    })),
  };
  return JSON.stringify(payload, null, 2) + '\n';
}

export function triggerTextDownload(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
