import { describe, expect, it } from 'vitest';
import { routeFromPath } from '../src/admin/lib/routes';

describe('routeFromPath', () => {
  it('maps deep links and trailing slashes', () => {
    expect(routeFromPath('/admin/keys')).toBe('keys');
    expect(routeFromPath('/admin/gateway-logs/')).toBe('gateway-logs');
  });

  it('uses providers for the admin root and unknown paths', () => {
    expect(routeFromPath('/admin')).toBe('providers');
    expect(routeFromPath('/admin/unknown')).toBe('providers');
  });
});
