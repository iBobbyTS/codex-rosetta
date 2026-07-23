import { describe, expect, it, vi } from 'vitest';
import {
  initializeConfiguration,
  launchGateway,
  probeConfiguration,
  setLocalMode,
  type InvokeCommand,
} from '../src/bootstrap/commands';

function fixedInvoke(mock: ReturnType<typeof vi.fn>): InvokeCommand {
  return mock as InvokeCommand;
}

describe('desktop bootstrap command boundary', () => {
  it('probes through the fixed command without arguments', async () => {
    const invoke = vi.fn().mockResolvedValue({ event: 'probe', state: 'ready' });

    await expect(probeConfiguration(fixedInvoke(invoke))).resolves.toEqual({
      event: 'probe',
      state: 'ready',
    });
    expect(invoke).toHaveBeenCalledWith('probe');
  });

  it('accepts a one-character password and clears it after successful initialization', async () => {
    const invoke = vi.fn().mockResolvedValue({
      event: 'initialized',
      state: 'ready_for_local_mode_confirmation',
    });
    const clearPassword = vi.fn();

    await initializeConfiguration('x', clearPassword, fixedInvoke(invoke));

    expect(invoke).toHaveBeenCalledWith('initialize', { adminPassword: 'x' });
    expect(clearPassword).toHaveBeenCalledOnce();
  });

  it('clears the password even when initialization fails', async () => {
    const invoke = vi.fn().mockRejectedValue('config_exists');
    const clearPassword = vi.fn();

    await expect(
      initializeConfiguration('secret', clearPassword, fixedInvoke(invoke)),
    ).rejects.toBe('config_exists');
    expect(clearPassword).toHaveBeenCalledOnce();
  });

  it('sends only an explicit boolean local-mode decision', async () => {
    const invoke = vi.fn().mockResolvedValue({ event: 'local_mode' });

    await setLocalMode(false, fixedInvoke(invoke));

    expect(invoke).toHaveBeenCalledWith('confirm_local_mode', { confirm: false });
  });

  it('starts through the fixed gateway command without a URL or command argument', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);

    await launchGateway(fixedInvoke(invoke));

    expect(invoke).toHaveBeenCalledWith('start_gateway');
  });

  it('rejects mismatched sidecar events instead of guessing the next state', async () => {
    const invoke = vi.fn().mockResolvedValue({ event: 'ready', state: 'ready' });

    await expect(probeConfiguration(fixedInvoke(invoke))).rejects.toThrow(
      'invalid_sidecar_response',
    );
  });
});
