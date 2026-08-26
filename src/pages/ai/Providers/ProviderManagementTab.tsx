import React, { useEffect, useState } from 'react';
import {
  Activity,
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Download,
  Eye,
  EyeOff,
  Globe2,
  KeyRound,
  LockKeyhole,
  Plus,
  Pencil,
  Power,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { getAIProviders, createAIProvider, updateAIProvider, deleteAIProvider, getAIProviderDeletePreview, testAIProvider, AIProvider } from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { ActionButton, ActionIconButton, ActionIconGroup, ActionLink } from '../../../components/ui/ActionIconButton';

interface ProviderTestResult {
  id: string;
  success: boolean;
  message: string;
  latency_ms?: number;
  sample_response?: string | null;
  model_tested?: string | null;
  error_code?: string | null;
}

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  helper: string;
  tone: 'indigo' | 'emerald' | 'amber' | 'slate';
}

const metricToneClasses: Record<MetricCardProps['tone'], string> = {
  indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300',
  emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300',
  amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300',
  slate: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

const DATA_REGION_OPTIONS = [
  { value: 'unknown', zh: '未配置', en: 'Not configured' },
  { value: 'global', zh: '全球', en: 'Global' },
  { value: 'cn', zh: '中国', en: 'China' },
  { value: 'us', zh: '美国', en: 'United States' },
  { value: 'eu', zh: '欧盟', en: 'European Union' },
] as const;

const MetricCard: React.FC<MetricCardProps> = ({ icon: Icon, label, value, helper, tone }) => (
  <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">{label}</p>
        <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</p>
      </div>
      <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${metricToneClasses[tone]}`}>
        <Icon className="h-4 w-4" />
      </span>
    </div>
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{helper}</p>
  </div>
);

const getErrorMessage = (error: unknown, fallback: string) => (
  error instanceof Error && error.message ? error.message : fallback
);

const getTestTitle = (result: ProviderTestResult, zh: boolean) => (
  result.success ? (zh ? '连接测试通过' : 'Connection test passed') : (zh ? '连接测试未通过' : 'Connection test failed')
);

const getTestDescription = (result: ProviderTestResult, zh: boolean) => {
  if (result.success) {
    return zh
      ? `安全网关已完成模型探测${result.model_tested ? ` · ${result.model_tested}` : ''}，Provider 可以正常响应。`
      : `The security gateway completed the model probe${result.model_tested ? ` · ${result.model_tested}` : ''}. The Provider is responding normally.`;
  }

  if (result.error_code === 'AI_SECURITY_CLASSIFICATION_DENIED') {
    return zh
      ? '安全网关拒绝了本次请求：Provider 允许的数据分类级别不足，请在编辑 Provider 中提高允许分类。'
      : 'The security gateway rejected this request because the Provider data-classification ceiling is too low. Edit the Provider to raise it.';
  }

  if (result.error_code === 'AI_SECURITY_POLICY_DISABLED') {
    return zh
      ? '安全网关当前未启用外部 AI 出口，请先在 AI 安全网关中启用。'
      : 'The external AI egress is disabled. Enable it in AI Security Gateway first.';
  }

  if (result.error_code === 'AI_AUTH_FAILED') {
    return zh
      ? 'Provider 已拒绝 API Key（HTTP 401/403）。请重新填写或轮换 API Key；认证失败不会继续重试。'
      : 'The Provider rejected the API key (HTTP 401/403). Re-enter or rotate the key; authentication failures are not retried.';
  }

  if (result.error_code === 'AI_PROVIDER_CIRCUIT_OPEN') {
    return zh
      ? 'Provider 因连续失败暂时熔断。请先修正 API Key、Base URL 或模型配置；保存新 API Key 会自动清除旧熔断，或等待冷却后重试。'
      : 'The Provider circuit is temporarily open after repeated failures. Fix the API key, Base URL, or model; saving a new key resets the circuit, or retry after cooldown.';
  }

  if (result.error_code === 'AI_HEALTH_BACKOFF') {
    return zh
      ? '刚刚已经执行过一次失败探测，系统正在短暂冷却。请修正 API Key 后保存，或等待冷却结束再重试。'
      : 'A failed probe just ran and the health backoff is active. Fix and save the API key, or retry after the cooldown.';
  }

  if (result.error_code === 'AI_MODEL_NOT_FOUND') {
    return zh
      ? 'Provider 找不到绑定模型或接口地址，请检查模型代码和 Base URL。'
      : 'The Provider could not find the bound model or endpoint. Check the model code and Base URL.';
  }

  if (result.error_code === 'AI_NETWORK_ERROR') {
    return zh
      ? '无法连接 Provider，请检查 Base URL、网络代理和 HTTPS 配置。'
      : 'The Provider could not be reached. Check the Base URL, network proxy, and HTTPS configuration.';
  }

  return zh
    ? '没有收到有效的模型响应，请检查 API Key、Base URL、绑定模型和安全网关策略。'
    : 'No valid model response was received. Check the API key, Base URL, bound model, and gateway policy.';
};

export const ProviderManagementTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const zh = language === 'zh';
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState('deepseek');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com');
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [defaultModelCode, setDefaultModelCode] = useState('deepseek-v4-flash');
  const [timeout, setTimeout] = useState(30);
  const [dataRegion, setDataRegion] = useState('unknown');
  const [allowedDataClassification, setAllowedDataClassification] = useState('PUBLIC');
  const [submitting, setSubmitting] = useState(false);

  const fetchProviders = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAIProviders();
      setProviders(data);
    } catch (err: unknown) {
      const message = getErrorMessage(err, zh ? '获取 Provider 列表失败' : 'Failed to load Providers');
      setError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchProviders();
  }, []);

  const handleTest = async (id: string) => {
    const provider = providers.find((item) => item.id === id);
    setTestingId(id);
    setTestResult(null);
    try {
      const res = await testAIProvider(id);
      const result: ProviderTestResult = {
        id,
        success: res.success,
        message: res.message,
        latency_ms: res.latency_ms,
        sample_response: res.sample_response,
        model_tested: res.model_tested,
        error_code: res.error_code,
      };
      setTestResult(result);
      // Keep the summary card in sync with the just-completed probe. The API
      // persists the health result, but the list is otherwise only refreshed
      // on mount/manual refresh, which could leave a stale AI_SECURITY_BLOCKED
      // badge visible after a successful test.
      setProviders((current) => current.map((item) => item.id === id
        ? {
            ...item,
            health_status: result.success ? 'healthy' : 'unhealthy',
            last_error_code: result.success ? null : (result.error_code || item.last_error_code),
          }
        : item));
      showToast(
        result.success
          ? (zh ? `${provider?.name || 'Provider'} 连接测试通过` : `${provider?.name || 'Provider'} connection test passed`)
          : (zh ? `${provider?.name || 'Provider'} 连接测试未通过` : `${provider?.name || 'Provider'} connection test failed`),
        result.success ? 'success' : 'error',
      );
    } catch (err: unknown) {
      const result: ProviderTestResult = {
        id,
        success: false,
        message: getErrorMessage(err, zh ? '测试连通性失败' : 'Connection test failed'),
      };
      setTestResult(result);
      showToast(result.message, 'error');
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    const provider = providers.find((item) => item.id === id);
    try {
      const preview = await getAIProviderDeletePreview(id);
      const summary = zh
        ? `${provider?.name || 'Provider'}：${preview.model_count || 0} 个模型、${preview.route_count || 0} 条路由引用。继续尝试删除？`
        : `${provider?.name || 'Provider'}: ${preview.model_count || 0} models and ${preview.route_count || 0} route references. Continue?`;
      if (!window.confirm(summary)) return;
    } catch {
      if (!window.confirm(zh ? '无法读取删除预览，仍要尝试删除吗？' : 'Delete preview failed. Try anyway?')) return;
    }

    setDeletingId(id);
    try {
      await deleteAIProvider(id);
      setProviders((current) => current.filter((item) => item.id !== id));
      if (testResult?.id === id) setTestResult(null);
      showToast(zh ? `${provider?.name || 'Provider'} 已删除` : `${provider?.name || 'Provider'} deleted`, 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, zh ? '删除失败' : 'Delete failed'), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const handleToggle = async (provider: AIProvider) => {
    try {
      const updated = await updateAIProvider(provider.id, { enabled: !provider.enabled });
      setProviders((current) => current.map((item) => item.id === updated.id ? updated : item));
      showToast(zh ? `${provider.name} 已${updated.enabled ? '启用' : '停用'}` : `${provider.name} ${updated.enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, zh ? '更新 Provider 状态失败' : 'Failed to update Provider status'), 'error');
    }
  };

  const openEdit = (provider: AIProvider) => {
    setEditingId(provider.id);
    setName(provider.name);
    setProviderType(provider.provider_type);
    setBaseUrl(provider.base_url || '');
    setApiKey('');
    setShowApiKey(false);
    setDefaultModelCode('');
    setTimeout(provider.timeout || 30);
    setDataRegion(provider.data_region || 'unknown');
    setAllowedDataClassification(provider.allowed_data_classification || 'PUBLIC');
    setShowModal(true);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingId) {
        await updateAIProvider(editingId, { name, provider_type: providerType, base_url: baseUrl || undefined, api_key: apiKey || undefined, timeout, data_region: dataRegion, allowed_data_classification: allowedDataClassification });
      } else {
        await createAIProvider({ name, provider_type: providerType, base_url: baseUrl || undefined, api_key: apiKey || undefined, default_model_code: defaultModelCode || undefined, timeout, data_region: dataRegion, enabled: true, allowed_data_classification: allowedDataClassification });
      }
      setShowModal(false);
      setEditingId(null);
      setName('');
      setApiKey('');
      setBaseUrl('https://api.deepseek.com');
      setShowApiKey(false);
      setDefaultModelCode('deepseek-v4-flash');
      setTimeout(30);
      setDataRegion('unknown');
      setAllowedDataClassification('PUBLIC');
      await fetchProviders();
      showToast(zh ? (editingId ? 'Provider 已更新' : 'Provider 已添加') : (editingId ? 'Provider updated' : 'Provider added'), 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, zh ? '添加 Provider 失败' : 'Failed to add Provider'), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const activeCount = providers.filter((provider) => provider.enabled).length;
  const securedCount = providers.filter((provider) => Boolean(provider.api_key_masked)).length;

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-violet-100/70 px-5 py-6 shadow-sm shadow-indigo-100/50 dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/50 dark:to-slate-900 dark:shadow-none sm:px-7 sm:py-7">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-indigo-300/20 blur-3xl dark:bg-indigo-500/10" />
        <div className="pointer-events-none absolute -bottom-32 left-1/3 h-64 w-64 rounded-full bg-violet-300/20 blur-3xl dark:bg-violet-500/10" />
        <div className="relative flex flex-col justify-between gap-6 xl:flex-row xl:items-center">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300">
              <Activity className="h-3.5 w-3.5" />
              {zh ? 'AI 基础设施 · Provider 管理' : 'AI Infrastructure · Provider Management'}
            </div>
            <h2 className="nx-page-title flex items-center gap-3 text-slate-950 dark:text-white">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-600/25">
                <Bot className="h-6 w-6" />
              </span>
              {zh ? 'AI Provider 供应商管理' : 'AI Provider Management'}
            </h2>
            <p className="nx-page-description mt-3 max-w-2xl text-slate-600 dark:text-slate-300">
              {zh
                ? '集中管理外部模型入口、密钥和默认模型。所有请求都会经过 AI 安全网关。'
                : 'Manage external model endpoints, keys, and default models in one place. Every request passes through the AI security gateway.'}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/75 px-2.5 py-1.5 font-medium shadow-sm shadow-indigo-100/50 dark:bg-slate-900/70 dark:shadow-none">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
                {zh ? 'API Key 使用 AES-256-GCM 加密存储' : 'API keys are encrypted with AES-256-GCM'}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/75 px-2.5 py-1.5 font-medium shadow-sm shadow-indigo-100/50 dark:bg-slate-900/70 dark:shadow-none">
                <LockKeyhole className="h-3.5 w-3.5 text-indigo-500" />
                {zh ? '外部请求统一走安全网关' : 'External requests use the security gateway'}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 self-start xl:self-center">
            <ActionLink
              href="/downloads/nexora-ai-provider-debug-manual.md"
              download="Nexora-AI-使用手册.md"
              aria-label={zh ? '下载 AI 使用手册' : 'Download AI user manual'}
              title={zh ? '下载 AI 接入与调试使用手册' : 'Download AI integration and troubleshooting manual'}
              icon={Download}
              variant="accent"
              size="md"
            >
              {zh ? '下载 AI 使用手册' : 'Download AI manual'}
            </ActionLink>
            <ActionButton
              type="button"
              icon={RefreshCw}
              iconClassName={loading ? 'animate-spin' : undefined}
              variant="default"
              size="md"
              onClick={() => void fetchProviders()}
            >
              {zh ? '刷新' : 'Refresh'}
            </ActionButton>
            <button
              type="button"
              onClick={() => { setEditingId(null); setApiKey(''); setShowApiKey(false); setDataRegion('unknown'); setAllowedDataClassification('PUBLIC'); setShowModal(true); }}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-slate-950"
            >
              <Plus className="h-4 w-4" />
              {zh ? '添加 Provider' : 'Add Provider'}
            </button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          icon={Bot}
          label={zh ? 'Provider 总数' : 'Total Providers'}
          value={providers.length}
          helper={zh ? '已登记的外部模型入口' : 'Registered external model endpoints'}
          tone="indigo"
        />
        <MetricCard
          icon={CheckCircle2}
          label={zh ? '已启用' : 'Enabled'}
          value={activeCount}
          helper={zh ? '当前可以接收请求' : 'Ready to receive requests'}
          tone="emerald"
        />
        <MetricCard
          icon={KeyRound}
          label={zh ? '密钥状态' : 'Key Status'}
          value={`${securedCount}/${providers.length}`}
          helper={zh ? '已配置并完成脱敏显示' : 'Configured and masked'}
          tone="amber"
        />
        <MetricCard
          icon={ShieldCheck}
          label={zh ? '安全通道' : 'Security Channel'}
          value="AES-256"
          helper={zh ? '所有外部 AI 请求经过网关' : 'All external AI requests use the gateway'}
          tone="slate"
        />
      </section>

      <section className="flex flex-col gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/65 px-4 py-4 dark:border-indigo-900/70 dark:bg-indigo-950/25 sm:flex-row sm:items-start sm:px-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-md shadow-indigo-600/20">
          <CircleAlert className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-100">{zh ? '关于“测试连通性”' : 'About “Test connectivity”'}</h3>
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-900/60 dark:text-indigo-300">
              {zh ? '不读取业务数据' : 'No business data'}
            </span>
          </div>
          <p className="mt-1.5 max-w-4xl text-xs leading-5 text-indigo-900/70 dark:text-indigo-200/70">
            {zh
              ? '测试会通过安全网关发送一条最小探测请求，仅验证 Provider、绑定模型和返回链路；不会携带设备、配置或业务数据。'
              : 'The test sends a minimal probe through the security gateway to verify the Provider, bound model, and response path. No device, configuration, or business data is included.'}
          </p>
          <p className="mt-2 text-[11px] text-indigo-900/55 dark:text-indigo-200/55">
            {zh ? '探测内容：' : 'Probe: '}
            <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px] text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-200">Reply with one short word: ok</code>
          </p>
        </div>
      </section>

      {error && (
        <div className="flex flex-col gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => void fetchProviders()} className="self-start rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-white dark:bg-rose-900/30 dark:text-rose-200 dark:hover:bg-rose-900/50 sm:self-auto">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {[0, 1].map((item) => (
            <div key={item} className="h-[380px] animate-pulse rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <div className="h-12 w-2/3 rounded-xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-6 h-28 rounded-2xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-4 h-24 rounded-2xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-6 h-10 rounded-xl bg-slate-100 dark:bg-slate-800" />
            </div>
          ))}
        </div>
      ) : providers.length === 0 ? (
        <div className="relative overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-14 text-center dark:border-slate-700 dark:bg-slate-900/60">
          <div className="pointer-events-none absolute left-1/2 top-0 h-32 w-64 -translate-x-1/2 rounded-full bg-indigo-100/70 blur-3xl dark:bg-indigo-900/20" />
          <span className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-500 dark:bg-indigo-950/50 dark:text-indigo-300">
            <Bot className="h-7 w-7" />
          </span>
          <h3 className="relative mt-4 text-base font-bold text-slate-800 dark:text-white">{zh ? '还没有 Provider' : 'No Providers yet'}</h3>
          <p className="relative mx-auto mt-1.5 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
            {zh ? '可添加多个供应商实例，并在模型管理与 Copilot 中自由切换。' : 'Add multiple provider instances and switch models from Model Management or Copilot.'}
          </p>
          <button type="button" onClick={() => { setEditingId(null); setApiKey(''); setShowApiKey(false); setDataRegion('unknown'); setAllowedDataClassification('PUBLIC'); setShowModal(true); }} className="relative mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700">
            <Plus className="h-4 w-4" />
            {zh ? '添加第一个 Provider' : 'Add your first Provider'}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {providers.map((provider) => {
            const result = testResult?.id === provider.id ? testResult : null;
            const isTesting = testingId === provider.id;
            const isDeleting = deletingId === provider.id;

            return (
              <article key={provider.id} className="group relative flex h-full min-h-[390px] flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm shadow-slate-200/50 transition duration-200 hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-100/50 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none dark:hover:border-indigo-800">
                <div className="h-1 bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-400" />
                <div className="flex flex-1 flex-col p-5 sm:p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-950 text-white shadow-md shadow-slate-900/10 dark:bg-indigo-500/20 dark:text-indigo-200">
                        <Bot className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-base font-bold text-slate-900 dark:text-white">{provider.name}</h3>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] ${provider.enabled ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
                            {provider.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')}
                          </span>
                        </div>
                        <p className="mt-1 text-xs font-semibold uppercase tracking-[0.12em] text-indigo-500 dark:text-indigo-300">{provider.provider_type}</p>
                      </div>
                    </div>
                    <ActionIconGroup label={zh ? 'Provider 操作' : 'Provider actions'}>
                      <ActionIconButton
                        icon={Pencil}
                        label={zh ? `编辑 ${provider.name}` : `Edit ${provider.name}`}
                        variant="accent"
                        disabled={isTesting || isDeleting}
                        onClick={() => openEdit(provider)}
                      />
                      <ActionIconButton
                        icon={Power}
                        label={provider.enabled ? (zh ? `停用 ${provider.name}` : `Disable ${provider.name}`) : (zh ? `启用 ${provider.name}` : `Enable ${provider.name}`)}
                        disabled={isTesting || isDeleting}
                        onClick={() => void handleToggle(provider)}
                      />
                      <ActionIconButton
                        icon={Trash2}
                        label={zh ? `删除 ${provider.name}` : `Delete ${provider.name}`}
                        variant="danger"
                        disabled={isDeleting}
                        iconClassName={isDeleting ? 'animate-pulse' : undefined}
                        onClick={() => void handleDelete(provider.id)}
                      />
                    </ActionIconGroup>
                  </div>

                  <p className="mt-3 truncate font-mono text-[11px] text-slate-400 dark:text-slate-500" title={provider.id}>{provider.id}</p>

                  <div className="mt-4 rounded-2xl border border-slate-100 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-950/50">
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500">{zh ? '连接配置' : 'Connection config'}</span>
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                        <LockKeyhole className="h-3 w-3" />
                        {zh ? '已加密' : 'Encrypted'}
                      </span>
                    </div>
                    <dl className="space-y-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <Globe2 className="h-4 w-4 shrink-0 text-slate-400" />
                        <dt className="w-20 shrink-0 text-xs text-slate-400">Base URL</dt>
                        <dd className="min-w-0 truncate font-mono text-xs text-slate-700 dark:text-slate-200" title={provider.base_url || undefined}>{provider.base_url || (zh ? '使用默认端点' : 'Default endpoint')}</dd>
                      </div>
                      <div className="flex min-w-0 items-center gap-3">
                        <KeyRound className="h-4 w-4 shrink-0 text-slate-400" />
                        <dt className="w-20 shrink-0 text-xs text-slate-400">API Key</dt>
                        <dd className="min-w-0 truncate font-mono text-xs text-slate-700 dark:text-slate-200">{provider.api_key_masked || (zh ? '未配置' : 'Not configured')}</dd>
                        <span className="ml-auto shrink-0 rounded-md bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">AES-256</span>
                      </div>
                    </dl>
                    <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
                      <span className={`rounded-full px-2 py-0.5 font-semibold ${provider.health_status === 'healthy' ? 'bg-emerald-100 text-emerald-700' : provider.health_status === 'unhealthy' ? 'bg-rose-100 text-rose-700' : 'bg-slate-200 text-slate-600'}`}>{zh ? '健康' : 'Health'}: {provider.health_status || 'unknown'}</span>
                      {provider.last_error_code && <span className="rounded-full bg-rose-50 px-2 py-0.5 font-mono text-rose-700">{provider.last_error_code}</span>}
                      {provider.data_region && (() => {
                        const region = DATA_REGION_OPTIONS.find((option) => option.value === provider.data_region?.toLowerCase());
                        return <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-700">{zh ? `区域: ${region?.zh || provider.data_region}` : `Region: ${region?.en || provider.data_region}`}</span>;
                      })()}
                    </div>
                  </div>

                  <div className={`mt-4 min-h-[92px] rounded-2xl border p-4 ${isTesting ? 'border-indigo-100 bg-indigo-50/60 dark:border-indigo-900/60 dark:bg-indigo-950/20' : result?.success ? 'border-emerald-100 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/20' : result ? 'border-rose-100 bg-rose-50/70 dark:border-rose-900/60 dark:bg-rose-950/20' : 'border-slate-100 bg-white dark:border-slate-800 dark:bg-slate-900'}`}>
                    {isTesting ? (
                      <div className="flex items-start gap-3">
                        <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-indigo-600 dark:text-indigo-300" />
                        <div>
                          <p className="text-sm font-bold text-indigo-900 dark:text-indigo-100">{zh ? '正在通过安全网关测试…' : 'Testing through security gateway…'}</p>
                          <p className="mt-1 text-xs leading-5 text-indigo-900/65 dark:text-indigo-200/65">{zh ? '正在发送最小探测请求，请稍候。' : 'Sending the minimal probe request. Please wait.'}</p>
                        </div>
                      </div>
                    ) : result ? (
                      <div className="flex items-start gap-3">
                        {result.success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-300" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600 dark:text-rose-300" />}
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className={`text-sm font-bold ${result.success ? 'text-emerald-900 dark:text-emerald-100' : 'text-rose-900 dark:text-rose-100'}`}>{getTestTitle(result, zh)}</p>
                            {typeof result.latency_ms === 'number' && <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${result.success ? 'bg-white/80 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200' : 'bg-white/80 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200'}`}>{result.latency_ms} ms</span>}
                          </div>
                          <p className={`mt-1 text-xs leading-5 ${result.success ? 'text-emerald-900/70 dark:text-emerald-200/70' : 'text-rose-900/70 dark:text-rose-200/70'}`}>{getTestDescription(result, zh)}</p>
                          {result.success && result.sample_response && (
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-emerald-800 dark:text-emerald-200">
                              <span className="font-semibold">{zh ? '模型响应' : 'Model response'}</span>
                              <code className="max-w-full truncate rounded-md bg-white/80 px-2 py-1 font-mono dark:bg-emerald-900/40">{result.sample_response}</code>
                            </div>
                          )}
                          {!result.success && result.error_code && <p className="mt-2 font-mono text-[10px] text-rose-700/70 dark:text-rose-200/70">{zh ? '错误标识' : 'Error code'}: {result.error_code}</p>}
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start gap-3">
                        <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                        <div>
                          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{zh ? '尚未进行连通性测试' : 'Connectivity has not been tested'}</p>
                          <p className="mt-1 text-xs leading-5 text-slate-400 dark:text-slate-500">{zh ? '测试只会发送一条不含业务数据的最小请求。' : 'The test sends only a minimal request without business data.'}</p>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="mt-5 flex items-center justify-between gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
                    <span className="inline-flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
                      <Clock3 className="h-3.5 w-3.5" />
                      {zh ? `超时 ${provider.timeout}s` : `Timeout ${provider.timeout}s`}
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleTest(provider.id)}
                      disabled={isTesting || isDeleting}
                      className="inline-flex items-center gap-2 rounded-xl bg-indigo-50 px-3.5 py-2 text-xs font-bold text-indigo-700 transition hover:bg-indigo-100 disabled:cursor-wait disabled:opacity-60 dark:bg-indigo-500/10 dark:text-indigo-300 dark:hover:bg-indigo-500/20"
                    >
                      {isTesting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                      {isTesting ? (zh ? '测试中…' : 'Testing…') : (zh ? '测试连通性' : 'Test connectivity')}
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="add-provider-title">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl shadow-slate-950/20 dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-6">
              <div>
                <div className="mb-2 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-500">
                  <Plus className="h-3.5 w-3.5" />
                  {zh ? '新增接入' : 'New connection'}
                </div>
                <h3 id="add-provider-title" className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">{zh ? (editingId ? '编辑 AI Provider' : '添加 AI Provider') : (editingId ? 'Edit AI Provider' : 'Add AI Provider')}</h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{zh ? '填写连接信息，密钥只会以加密形式保存。' : 'Add connection details. The key is stored only in encrypted form.'}</p>
              </div>
              <button type="button" onClick={() => { setEditingId(null); setShowApiKey(false); setShowModal(false); }} aria-label={zh ? '关闭' : 'Close'} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="overflow-y-auto px-5 py-5 sm:px-6">
              <div className="space-y-4">
                <div>
                  <label htmlFor="provider-data-region" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '数据区域' : 'Data region'}</label>
                  <select
                    id="provider-data-region"
                    value={dataRegion}
                    onChange={(e) => setDataRegion(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  >
                    {DATA_REGION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.value} · {zh ? option.zh : option.en}</option>)}
                  </select>
                  <p className="mt-1.5 text-[10px] text-slate-400">{zh ? '按供应商实际数据驻留/合规区域选择；不确定时保持未配置。' : 'Choose the Provider\'s actual data-residency/compliance region; keep Not configured when uncertain.'}</p>
                </div>

                <div>
                  <label htmlFor="provider-name" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? 'Provider 名称' : 'Provider name'}</label>
                  <input id="provider-name" type="text" required placeholder={zh ? '例如：DeepSeek 官方' : 'e.g. DeepSeek official'} value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '供应商类型' : 'Provider type'}</label>
                  <select value={providerType} onChange={(e) => {
                    const next = e.target.value;
                    setProviderType(next);
                    if (next === 'deepseek') { setBaseUrl('https://api.deepseek.com'); setDefaultModelCode('deepseek-v4-flash'); }
                    else if (next === 'openai' || next === 'azure_openai') { setBaseUrl('https://api.openai.com/v1'); setDefaultModelCode('gpt-4o'); }
                    else if (next === 'ollama' || next === 'local') { setBaseUrl('http://127.0.0.1:11434/v1'); setDefaultModelCode('llama3.1'); }
                    else { setBaseUrl(''); setDefaultModelCode(''); }
                  }} className="w-full rounded-xl border border-indigo-200 bg-indigo-50/70 px-3.5 py-2.5 text-sm font-semibold text-indigo-950 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-100">
                    <option value="deepseek">DeepSeek（官方适配器）</option>
                    <option value="openai">OpenAI</option>
                    <option value="openai_compatible">OpenAI-compatible 自定义端点</option>
                    <option value="azure_openai">Azure OpenAI</option>
                    <option value="qwen">通义千问兼容端点</option>
                    <option value="ollama">Ollama / 本地</option>
                    <option value="local">Local OpenAI-compatible</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="provider-base-url" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">Base URL</label>
                  <input id="provider-base-url" type="url" placeholder="https://api.deepseek.com" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label htmlFor="provider-api-key" className="block text-xs font-bold text-slate-700 dark:text-slate-300">API Key</label>
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400"><LockKeyhole className="h-3 w-3" />AES-256-GCM</span>
                  </div>
                  <div className="relative">
                    <input id="provider-api-key" type={showApiKey ? 'text' : 'password'} required={providerType !== 'ollama' && providerType !== 'local'} placeholder={providerType === 'ollama' || providerType === 'local' ? (zh ? '本地端点可留空' : 'Optional for local endpoint') : 'sk-...'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 pr-11 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                    <button
                      type="button"
                      onClick={() => setShowApiKey((visible) => !visible)}
                      aria-label={showApiKey ? (zh ? '隐藏 API Key' : 'Hide API Key') : (zh ? '显示 API Key' : 'Show API Key')}
                      title={showApiKey ? (zh ? '隐藏本次输入的 API Key' : 'Hide the newly entered API Key') : (zh ? '显示本次输入的 API Key' : 'Show the newly entered API Key')}
                      className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-indigo-600 dark:hover:bg-slate-800 dark:hover:text-indigo-300"
                    >
                      {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-[1fr_150px]">
                  <div>
                    <label htmlFor="provider-model-code" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '绑定模型' : 'Bound model'} <span className="font-normal text-slate-400">(Model Code)</span></label>
                    <input id="provider-model-code" type="text" placeholder="deepseek-v4-flash" value={defaultModelCode} onChange={(e) => setDefaultModelCode(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                    <p className="mt-1.5 text-[10px] text-slate-400">{zh ? '将自动注册至模型列表与路由' : 'Registered in models and routes automatically'}</p>
                  </div>
                  <div>
                    <label htmlFor="provider-timeout" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '超时（秒）' : 'Timeout (sec)'}</label>
                    <input id="provider-timeout" type="number" min={5} max={300} value={timeout} onChange={(e) => setTimeout(Number(e.target.value) || 30)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                  </div>
                </div>

                <div>
                  <label htmlFor="provider-allowed-data-classification" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{zh ? '允许数据分类' : 'Allowed data classification'}</label>
                  <select
                    id="provider-allowed-data-classification"
                    value={allowedDataClassification}
                    onChange={(e) => setAllowedDataClassification(e.target.value)}
                    className="w-full rounded-xl border border-indigo-200 bg-indigo-50/70 px-3.5 py-2.5 text-sm font-semibold text-indigo-950 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-100"
                  >
                    <option value="PUBLIC">PUBLIC · 公开</option>
                    <option value="INTERNAL">INTERNAL · 内部</option>
                    <option value="CONFIDENTIAL">CONFIDENTIAL · 机密</option>
                  </select>
                  <p className="mt-1.5 text-[10px] text-slate-400">{zh ? '网关不会向该 Provider 发送高于此级别的数据。' : 'The gateway will not send data above this level to the Provider.'}</p>
                </div>

              </div>

              <div className="mt-6 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 dark:border-slate-800 sm:flex-row sm:justify-end">
                <button type="button" onClick={() => { setEditingId(null); setShowApiKey(false); setShowModal(false); }} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-200">{zh ? '取消' : 'Cancel'}</button>
                <button type="submit" disabled={submitting} className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">
                  {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
                  {submitting ? (zh ? '保存中…' : 'Saving…') : (editingId ? (zh ? '保存修改' : 'Save changes') : (zh ? '确认添加' : 'Add Provider'))}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
