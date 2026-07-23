export const routes = [
  { id: 'providers', path: '/admin/providers', labelKey: 'nav.providers' },
  { id: 'models', path: '/admin/models', labelKey: 'nav.models' },
  { id: 'keys', path: '/admin/keys', labelKey: 'nav.keys' },
  { id: 'tools', path: '/admin/tools', labelKey: 'nav.tools' },
  { id: 'network-search', path: '/admin/network-search', labelKey: 'nav.networkSearch' },
  { id: 'dashboard', path: '/admin/dashboard', labelKey: 'nav.dashboard' },
  { id: 'logs', path: '/admin/logs', labelKey: 'nav.logs' },
  { id: 'gateway-logs', path: '/admin/gateway-logs', labelKey: 'nav.gatewayLogs' },
] as const;

export type RouteId = (typeof routes)[number]['id'];

export function routeFromPath(pathname: string): RouteId {
  const normalized = pathname.replace(/\/$/, '') || '/admin';
  return routes.find((route) => route.path === normalized)?.id ?? 'providers';
}
