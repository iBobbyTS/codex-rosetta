<script lang="ts">
  import CredentialEditor from '../../src/admin/components/CredentialEditor.svelte';

  let { initialValue = '' }: { initialValue?: string } = $props();
  let value = $state('');

  $effect(() => {
    value = initialValue;
  });
</script>

<CredentialEditor ariaLabel="Credential" clearLabel="Clear credential" {value} onchange={(next) => value = next} placeholder="Secret" />
<output>{value}</output>
