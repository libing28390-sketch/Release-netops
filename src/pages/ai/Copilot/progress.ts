import type { AssistantProcessStep } from '../../../api/ai';

export function formatCopilotDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts: string[] = [];

  if (hours > 0) parts.push(`${hours}小时`);
  if (minutes > 0 || hours > 0) parts.push(`${minutes}分钟`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}秒`);

  return `已处理 ${parts.join(' ')}`;
}

export function upsertCopilotProcessStep(
  steps: AssistantProcessStep[],
  nextStep: AssistantProcessStep,
): AssistantProcessStep[] {
  const existingIndex = steps.findIndex((step) => step.id === nextStep.id);
  if (existingIndex === -1) return [...steps, nextStep];

  return steps.map((step, index) => (index === existingIndex ? { ...step, ...nextStep } : step));
}
