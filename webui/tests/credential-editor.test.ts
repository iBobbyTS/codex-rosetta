// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import CredentialEditorHarness from './fixtures/CredentialEditorHarness.svelte';

describe('CredentialEditor', () => {
  it('edits an empty controlled value through a password input', async () => {
    render(CredentialEditorHarness);

    const input = screen.getByLabelText('Credential');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('placeholder', 'Secret');

    for (const value of ['f', 'fr', 'fresh', 'fresh-secret']) {
      await fireEvent.input(input, { target: { value } });
      expect(screen.getByLabelText('Credential')).toBe(input);
      expect(input).toHaveAttribute('type', 'password');
    }
    expect(screen.getByRole('status')).toHaveTextContent('fresh-secret');
    await fireEvent.blur(input);
    expect(screen.getByRole('textbox', { name: 'Credential' })).toHaveValue('fres•••cret');
  });

  it('shows only the first and last four characters of a long value in a read-only display', async () => {
    render(CredentialEditorHarness, { initialValue: 'abcd-middle-wxyz' });

    const display = screen.getByRole('textbox', { name: 'Credential' });
    expect(display).toHaveValue('abcd•••wxyz');
    expect(display).toHaveAttribute('readonly');
    await fireEvent.click(display);
    expect(screen.getByRole('textbox', { name: 'Credential' })).toHaveAttribute('readonly');
    expect(screen.queryByLabelText('Credential', { selector: 'input[type="password"]' })).not.toBeInTheDocument();
  });

  it('clears only the controlled value and returns to an empty password input', async () => {
    render(CredentialEditorHarness, { initialValue: 'abcd-middle-wxyz' });

    await fireEvent.click(screen.getByRole('button', { name: 'Clear credential' }));
    expect(screen.getByRole('status').textContent).toBe('');
    const input = screen.getByLabelText('Credential');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveValue('');
  });

  it.each([
    ['a', '•'],
    ['ab', 'a•'],
    ['abc', 'a••'],
    ['abcd', 'a••d'],
    ['abcde', 'a•••e'],
    ['abcdef', 'ab•••f'],
    ['abcdefg', 'ab••••g'],
    ['abcdefgh', 'ab••••gh'],
  ])('hides at least half of a %s short value', (value, expected) => {
    render(CredentialEditorHarness, { initialValue: value });
    expect(screen.getByRole('textbox', { name: 'Credential' })).toHaveValue(expected);
  });

  it.each(['***', 'abcd***wxyz', '${OPENAI_API_KEY}'])('preserves the canonical backend mask or placeholder %s', (value) => {
    render(CredentialEditorHarness, { initialValue: value });
    expect(screen.getByRole('textbox', { name: 'Credential' })).toHaveValue(value);
  });
});
