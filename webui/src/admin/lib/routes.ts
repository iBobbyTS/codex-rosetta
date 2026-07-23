export const routes = [
  { id: 'providers', path: '/admin/providers', label: 'Providers', labelKey: 'nav.providers' },
  { id: 'models', path: '/admin/models', label: 'Models', labelKey: 'nav.models' },
  { id: 'keys', path: '/admin/keys', label: 'API Keys', labelKey: 'nav.keys' },
  { id: 'tools', path: '/admin/tools', label: 'Tools', labelKey: 'nav.tools' },
  { id: 'network-search', path: '/admin/network-search', label: 'Web Search', labelKey: 'nav.networkSearch' },
  { id: 'dashboard', path: '/admin/dashboard', label: 'Dashboard', labelKey: 'nav.dashboard' },
  { id: 'logs', path: '/admin/logs', label: 'Request Log', labelKey: 'nav.logs' },
  { id: 'gateway-logs', path: '/admin/gateway-logs', label: 'Gateway Logs', labelKey: 'nav.gatewayLogs' },
] as const;

export type RouteId = (typeof routes)[number]['id'];

export function routeFromPath(pathname: string): RouteId {
  const normalized = pathname.replace(/\/$/, '') || '/admin';
  return routes.find((route) => route.path === normalized)?.id ?? 'providers';
}
