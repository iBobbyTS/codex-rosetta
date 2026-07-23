const anthropic = new URL('../assets/provider-logos/anthropic.svg', import.meta.url).href;
const deepseek = new URL('../assets/provider-logos/deepseek.svg', import.meta.url).href;
const google = new URL('../assets/provider-logos/google.svg', import.meta.url).href;
const minimax = new URL('../assets/provider-logos/minimax.svg', import.meta.url).href;
const moonshot = new URL('../assets/provider-logos/moonshot.svg', import.meta.url).href;
const openai = new URL('../assets/provider-logos/openai.svg', import.meta.url).href;
const opencode = new URL('../assets/provider-logos/opencode.png', import.meta.url).href;
const openrouter = new URL('../assets/provider-logos/openrouter.svg', import.meta.url).href;
const qwen = new URL('../assets/provider-logos/qwen.svg', import.meta.url).href;
const volcengine = new URL('../assets/provider-logos/volcengine.svg', import.meta.url).href;
const xai = new URL('../assets/provider-logos/xai.svg', import.meta.url).href;
const zhipu = new URL('../assets/provider-logos/zhipu.svg', import.meta.url).href;

const logos: Readonly<Record<string, string>> = {
  anthropic,
  deepseek,
  google,
  'minimax--anthropic': minimax,
  'minimax--openai_chat': minimax,
  moonshot,
  openai,
  openai_responses: openai,
  opencode_go: opencode,
  'openrouter--anthropic': openrouter,
  'openrouter--openai_chat': openrouter,
  qwen,
  'volcengine--openai_chat': volcengine,
  'volcengine--openai_responses': volcengine,
  xai,
  zhipu,
};

export function providerLogo(shimName?: string): string {
  return shimName ? logos[shimName] ?? '' : '';
}

export function providerLogoNeedsDarkInversion(shimName?: string): boolean {
  return Boolean(shimName && shimName !== 'opencode_go' && logos[shimName]);
}

export const bundledProviderLogoNames = Object.freeze(Object.keys(logos));
