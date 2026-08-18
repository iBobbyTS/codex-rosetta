type PlanPresentation = { label: string; className: string };

function normalizePlanKey(planType: string): string {
  const normalized = planType.trim().toLowerCase();
  if (!normalized) return 'free';
  if (normalized.includes('api')) return 'api_key';
  if (normalized.includes('enterprise')) return 'enterprise';
  if (normalized.includes('business')) return 'business';
  if (normalized.includes('team')) return 'team';
  if (normalized.includes('edu')) return 'edu';
  if (normalized.includes('go')) return 'go';
  if (normalized.includes('plus')) return 'plus';
  if (normalized.includes('pro')) return 'pro';
  if (normalized.includes('free')) return 'free';
  return normalized;
}

function normalizeProTier(planType: string): 'lite' | 'max' | null {
  const compact = planType.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
  if (['prolite', 'pro5x', 'codexpro5x'].includes(compact) || compact.endsWith('chatgptprolite')) return 'lite';
  if (['promax', 'pro20x', 'codexpro20x'].includes(compact) || compact.endsWith('chatgptpromax')) return 'max';
  return null;
}

const PLAN_PRESENTATIONS: Record<string, PlanPresentation> = {
  api_key: { label: 'API', className: 'api' },
  enterprise: { label: 'Enterprise', className: 'team' },
  business: { label: 'Business', className: 'team' },
  team: { label: 'Team', className: 'team' },
  edu: { label: 'Edu', className: 'team' },
  go: { label: 'Go', className: 'plus' },
  plus: { label: 'Plus', className: 'plus' },
  free: { label: 'Free', className: 'free' },
};

export function getCodexPlanPresentation(planType: string | undefined): PlanPresentation {
  const raw = planType ?? '';
  const key = normalizePlanKey(raw);
  if (key === 'pro') return { label: normalizeProTier(raw) === 'lite' ? 'Pro 5x' : 'Pro 20x', className: 'pro' };
  return PLAN_PRESENTATIONS[key] ?? { label: raw.trim() || 'Free', className: 'free' };
}
