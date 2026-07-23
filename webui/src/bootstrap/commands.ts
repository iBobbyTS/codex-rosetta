import { invoke } from '@tauri-apps/api/core';

export interface BootstrapResult {
  event: string;
  state?: string | null;
  code?: string | null;
}

export type InvokeCommand = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;

function validateEvent(result: BootstrapResult, event: string): BootstrapResult {
  if (result.event !== event) {
    throw new Error('invalid_sidecar_response');
  }
  return result;
}

export async function probeConfiguration(
  invokeCommand: InvokeCommand = invoke,
): Promise<BootstrapResult> {
  return validateEvent(await invokeCommand<BootstrapResult>('probe'), 'probe');
}

export async function initializeConfiguration(
  adminPassword: string,
  clearPassword: () => void,
  invokeCommand: InvokeCommand = invoke,
): Promise<BootstrapResult> {
  try {
    return validateEvent(
      await invokeCommand<BootstrapResult>('initialize', { adminPassword }),
      'initialized',
    );
  } finally {
    clearPassword();
  }
}

export async function setLocalMode(
  confirm: boolean,
  invokeCommand: InvokeCommand = invoke,
): Promise<BootstrapResult> {
  return validateEvent(
    await invokeCommand<BootstrapResult>('confirm_local_mode', { confirm }),
    'local_mode',
  );
}

export async function launchGateway(invokeCommand: InvokeCommand = invoke): Promise<void> {
  await invokeCommand<void>('start_gateway');
}
