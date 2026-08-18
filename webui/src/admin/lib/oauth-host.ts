export function isSupportedOAuthHost(hostname: string): boolean {
  return hostname.trim().toLowerCase() === 'localhost';
}
