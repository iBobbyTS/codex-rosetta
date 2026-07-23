// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const commands = vi.hoisted(() => ({
  initializeConfiguration: vi.fn(),
  launchGateway: vi.fn(),
  probeConfiguration: vi.fn(),
  setLocalMode: vi.fn(),
}));

vi.mock('../src/bootstrap/commands', () => commands);

import BootstrapApp from '../src/bootstrap/App.svelte';

beforeEach(() => {
  vi.clearAllMocks();
  commands.launchGateway.mockResolvedValue(undefined);
  commands.setLocalMode.mockResolvedValue({ event: 'local_mode' });
});

describe('desktop bootstrap state machine', () => {
  it.each([
    ['Enable local mode', true],
    ['Not now', false],
  ] as const)(
    'routes a pre-existing unconfirmed config through %s and then starts',
    async (buttonName, choice) => {
      commands.probeConfiguration.mockResolvedValue({
        event: 'probe',
        state: 'needs_local_mode_confirmation',
      });
      render(BootstrapApp);

      await fireEvent.click(await screen.findByRole('button', { name: buttonName }));

      await waitFor(() => expect(commands.setLocalMode).toHaveBeenCalledWith(choice));
      expect(commands.launchGateway).toHaveBeenCalledOnce();
    },
  );
});
