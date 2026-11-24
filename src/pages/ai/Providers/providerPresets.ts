interface ProviderPreset {
  id: string;
  label: string;
  providerType: string;
  baseUrl?: string;
  modelCode?: string;
  dataRegion?: 'cn';
  exampleUrl?: string;
  endpointPattern?: RegExp;
  helpKey?: string;
}

interface ProviderPresetGroup {
  labelKey: string;
  presets: ProviderPreset[];
}

export const providerPresetGroups: ProviderPresetGroup[] = [
  {
    labelKey: 'ai.provider.preset.group.cn',
    presets: [
      { id: 'deepseek', label: 'DeepSeek', providerType: 'deepseek', baseUrl: 'https://api.deepseek.com', modelCode: 'deepseek-flash' },
      { id: 'qwen', label: 'ai.provider.preset.qwen', providerType: 'qwen', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', modelCode: 'qwen-plus', dataRegion: 'cn' },
      { id: 'volcengine', label: 'ai.provider.preset.volcengine', providerType: 'openai_compatible', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', dataRegion: 'cn', helpKey: 'ai.provider.preset.volcengineHelp' },
      { id: 'hunyuan', label: 'ai.provider.preset.hunyuan', providerType: 'openai_compatible', baseUrl: 'https://api.hunyuan.cloud.tencent.com/v1' },
      { id: 'tokenhub', label: 'ai.provider.preset.tokenhub', providerType: 'openai_compatible', baseUrl: 'https://tokenhub.tencentcloudmaas.com/v1', dataRegion: 'cn' },
      { id: 'qianfan', label: 'ai.provider.preset.qianfan', providerType: 'openai_compatible', baseUrl: 'https://qianfan.baidubce.com/v2' },
      { id: 'kimi', label: 'ai.provider.preset.kimi', providerType: 'openai_compatible', baseUrl: 'https://api.moonshot.cn/v1' },
      { id: 'zhipu', label: 'ai.provider.preset.zhipu', providerType: 'openai_compatible', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
      { id: 'minimax', label: 'MiniMax', providerType: 'openai_compatible', baseUrl: 'https://api.minimax.cn/v1' },
      { id: 'siliconflow', label: 'ai.provider.preset.siliconflow', providerType: 'openai_compatible', baseUrl: 'https://api.siliconflow.cn/v1' },
    ],
  },
  {
    labelKey: 'ai.provider.preset.group.international',
    presets: [
      { id: 'openai', label: 'OpenAI', providerType: 'openai', baseUrl: 'https://api.openai.com/v1', modelCode: 'gpt-4o' },
      { id: 'anthropic', label: 'Anthropic Claude', providerType: 'anthropic', baseUrl: 'https://api.anthropic.com/v1' },
      { id: 'gemini', label: 'Google Gemini API', providerType: 'openai_compatible', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai' },
      { id: 'xai', label: 'xAI Grok', providerType: 'openai_compatible', baseUrl: 'https://api.x.ai/v1' },
      { id: 'mistral', label: 'Mistral AI', providerType: 'openai_compatible', baseUrl: 'https://api.mistral.ai/v1' },
      { id: 'cohere', label: 'Cohere', providerType: 'openai_compatible', baseUrl: 'https://api.cohere.ai/compatibility/v1' },
    ],
  },
  {
    labelKey: 'ai.provider.preset.group.cloud',
    presets: [
      {
        id: 'azure_openai', label: 'Azure OpenAI / Microsoft Foundry', providerType: 'azure_openai',
        exampleUrl: 'https://your-resource.openai.azure.com/openai/v1', helpKey: 'ai.provider.preset.azureHelp',
      },
      {
        id: 'bedrock', label: 'AWS Bedrock', providerType: 'openai_compatible',
        exampleUrl: 'https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1', helpKey: 'ai.provider.preset.bedrockHelp',
        endpointPattern: /^https:\/\/bedrock-runtime\.[\w-]+\.amazonaws\.com(?:\.cn)?\/openai\/v1$/i,
      },
      {
        id: 'vertex', label: 'Google Cloud Vertex AI', providerType: 'openai_compatible',
        exampleUrl: 'https://aiplatform.googleapis.com/v1/projects/YOUR_PROJECT/locations/global/endpoints/openapi', helpKey: 'ai.provider.preset.vertexHelp',
        endpointPattern: /^https:\/\/(?:[\w-]+-)?aiplatform\.googleapis\.com\/v1(?:beta1)?\/projects\/[^/]+\/locations\/[^/]+\/endpoints\/(?:openapi|\d+)$/i,
      },
    ],
  },
  {
    labelKey: 'ai.provider.preset.group.hosted',
    presets: [
      { id: 'openrouter', label: 'OpenRouter', providerType: 'openai_compatible', baseUrl: 'https://openrouter.ai/api/v1' },
      { id: 'groq', label: 'Groq', providerType: 'openai_compatible', baseUrl: 'https://api.groq.com/openai/v1' },
      { id: 'together', label: 'Together AI', providerType: 'openai_compatible', baseUrl: 'https://api.together.ai/v1' },
      { id: 'fireworks', label: 'Fireworks AI', providerType: 'openai_compatible', baseUrl: 'https://api.fireworks.ai/inference/v1' },
      { id: 'huggingface', label: 'Hugging Face Inference Providers', providerType: 'openai_compatible', baseUrl: 'https://router.huggingface.co/v1' },
    ],
  },
  {
    labelKey: 'ai.provider.preset.group.custom',
    presets: [
      { id: 'ollama', label: 'Ollama', providerType: 'ollama', baseUrl: 'http://127.0.0.1:11434/v1', modelCode: 'llama3.1' },
      { id: 'local', label: 'ai.provider.editor.local', providerType: 'local', baseUrl: 'http://127.0.0.1:11434/v1', modelCode: 'llama3.1' },
      { id: 'openai_compatible', label: 'ai.provider.editor.compatible', providerType: 'openai_compatible', exampleUrl: 'https://your-endpoint.example/v1' },
    ],
  },
];

const presets = providerPresetGroups.flatMap((group) => group.presets);

export const defaultProviderPreset = providerPresetGroups[0].presets[0];

export function getProviderPreset(id: string) {
  return presets.find((preset) => preset.id === id);
}

export function identifyProviderPreset(providerType: string, baseUrl?: string | null) {
  if (providerType !== 'openai_compatible') return getProviderPreset(providerType);

  const endpoint = (baseUrl ?? '').replace(/\/+$/, '').replace(/\/chat\/completions$/, '');
  return presets.find((preset) => preset.providerType === providerType && (preset.baseUrl === endpoint || preset.endpointPattern?.test(endpoint)))
    ?? getProviderPreset('openai_compatible');
}
