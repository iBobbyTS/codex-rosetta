<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import { api } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';

  type InputOption = { value: string; label?: string };
  type ProfileInput = {
    id: string;
    label_i18n?: string;
    type?: string;
    default?: string;
    visible_when?: string[];
    options?: InputOption[];
    readonly?: boolean;
    ui_hidden?: boolean;
  };
  type Placement = { normal_mode_i18n?: string; code_mode_i18n?: string };
  type ToolItem = {
    id: string;
    name?: string;
    type?: string;
    namespace_id?: string;
    policy_id?: string;
    summary_i18n?: string;
    description_i18n?: string;
    note_i18n?: string;
    note_visible_when?: string[];
    profile_inputs?: ProfileInput[];
    codex_placement?: Placement;
    ui_hidden?: boolean;
  };
  type CatalogGroup = { id: string; item_ids: string[] };
  type NamespacePlacement = { namespace_id: string; child_ids: string[] };
  type Catalog = {
    items?: ToolItem[];
    placements?: {
      groups?: CatalogGroup[];
      namespaces?: NamespacePlacement[];
    };
  };
  type ProfileApiType = 'chat' | 'responses' | 'anthropic' | 'google';
  type Profile = {
    id: string;
    name: string;
    api_types: ProfileApiType[];
    tools: Record<string, string>;
    inputs: Record<string, Record<string, string>>;
    readonly: boolean;
  };
  type ProfilesResponse = {
    profiles?: Profile[];
    supported_states?: Record<string, string[]>;
    references?: Record<string, string[]>;
  };
  type FilterId = 'all' | 'exec_expansion' | 'function' | 'namespace' | 'rosetta_injection';
  type ResolvedGroup = { id: string; items: ToolItem[] };

  const filterOptions: Array<{ id: FilterId; labelKey: string }> = [
    { id: 'all', labelKey: 'tools.filter.all' },
    { id: 'exec_expansion', labelKey: 'tools.filter.exec_expansion' },
    { id: 'function', labelKey: 'tools.filter.function' },
    { id: 'namespace', labelKey: 'tools.filter.namespace' },
    { id: 'rosetta_injection', labelKey: 'tools.filter.rosetta_injection' },
  ];
  const profileApiTypeOptions: Array<{ value: ProfileApiType; labelKey: string }> = [
    { value: 'chat', labelKey: 'protocol.chat' },
    { value: 'responses', labelKey: 'protocol.responses' },
    { value: 'anthropic', labelKey: 'protocol.anthropic' },
    { value: 'google', labelKey: 'tools.protocol.google' },
  ];

  let catalog = $state<Catalog>({});
  let profilesData = $state<ProfilesResponse>({});
  let selectedId = $state('');
  let profileApiTypes = $state<ProfileApiType[]>(['chat']);
  let toolDraft = $state<Record<string, string>>({});
  let inputDraft = $state<Record<string, Record<string, string>>>({});
  let cloneName = $state('');
  let cloneOpen = $state(false);
  let filter = $state<FilterId>('all');
  let detailId = $state('');
  let expandedNamespaces = $state<string[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let dirty = $state(false);
  let error = $state('');
  let notice = $state('');

  let selected = $derived((profilesData.profiles ?? []).find((profile) => profile.id === selectedId));
  let detail = $derived((catalog.items ?? []).find((item) => item.id === detailId));
  let itemIndex = $derived(new Map((catalog.items ?? []).map((item) => [item.id, item])));
  let namespaceIndex = $derived(new Map(
    (catalog.placements?.namespaces ?? []).map((placement) => [placement.namespace_id, placement]),
  ));
  let visibleGroups = $derived.by((): ResolvedGroup[] =>
    (catalog.placements?.groups ?? [])
      .filter((group) => filter === 'all' || group.id === filter)
      .map((group) => ({
        id: group.id,
        items: group.item_ids
          .map((id) => itemIndex.get(id))
          .filter((item): item is ToolItem => Boolean(item && !item.ui_hidden)),
      }))
      .filter((group) => group.items.length > 0),
  );
  let visibleToolCount = $derived(visibleGroups.reduce(
    (count, group) => count + group.items.reduce(
      (groupCount, item) => groupCount + 1 + (item.type === 'namespace' ? namespaceChildren(item.id).length : 0),
      0,
    ),
    0,
  ));

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);

  function namespaceChildren(namespaceId: string): ToolItem[] {
    return (namespaceIndex.get(namespaceId)?.child_ids ?? [])
      .map((id) => itemIndex.get(id))
      .filter((item): item is ToolItem => Boolean(item && !item.ui_hidden));
  }

  function resetExpandedNamespaces(): void {
    expandedNamespaces = (catalog.placements?.namespaces ?? [])
      .map((placement) => placement.namespace_id)
      .filter((namespaceId) => toolDraft[namespaceId] !== 'disabled');
  }

  function selectProfile(id: string): void {
    const profile = (profilesData.profiles ?? []).find((item) => item.id === id);
    if (!profile) return;
    selectedId = id;
    profileApiTypes = [...profile.api_types];
    toolDraft = { ...profile.tools };
    inputDraft = JSON.parse(JSON.stringify(profile.inputs ?? {})) as Record<string, Record<string, string>>;
    resetExpandedNamespaces();
    dirty = false;
    error = '';
  }

  function setFilter(nextFilter: FilterId): void {
    filter = nextFilter;
    const group = (catalog.placements?.groups ?? []).find((item) => item.id === nextFilter);
    const firstId = nextFilter === 'all'
      ? catalog.placements?.groups?.[0]?.item_ids[0]
      : group?.item_ids[0];
    detailId = firstId ?? '';
  }

  function toggleProfileApiType(value: ProfileApiType, checked: boolean): void {
    const next = new Set(profileApiTypes);
    checked ? next.add(value) : next.delete(value);
    if (!next.size) return;
    profileApiTypes = profileApiTypeOptions.map((option) => option.value).filter((item) => next.has(item));
    dirty = true;
  }

  async function load(signal?: AbortSignal): Promise<void> {
    try {
      const [nextCatalog, nextProfiles] = await Promise.all([
        api.get<Catalog>('/admin/api/tools/catalog', signal),
        api.get<ProfilesResponse>('/admin/api/tools/profiles', signal),
      ]);
      catalog = nextCatalog;
      profilesData = nextProfiles;
      const keep = nextProfiles.profiles?.some((item) => item.id === selectedId)
        ? selectedId
        : nextProfiles.profiles?.[0]?.id ?? '';
      selectProfile(keep);
      detailId ||= nextCatalog.placements?.groups?.[0]?.item_ids[0] ?? '';
      error = '';
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) error = message(cause);
    } finally {
      loading = false;
    }
  }

  async function saveAs(id: string): Promise<void> {
    if (!id.trim()) {
      error = t('tools.profileNameRequired');
      return;
    }
    busy = true;
    error = '';
    notice = '';
    try {
      await api.put(`/admin/api/tools/profiles/${encodeURIComponent(id.trim())}`, {
        api_types: profileApiTypes,
        tools: toolDraft,
        inputs: inputDraft,
      });
      notice = t('tools.profileSaved', { name: id.trim() });
      selectedId = id.trim();
      await load();
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  async function createCopy(): Promise<void> {
    await saveAs(cloneName);
    if (!error) cloneOpen = false;
  }

  async function remove(): Promise<void> {
    if (!selected || selected.readonly || !confirm(t('confirm.deleteToolProfile', { name: selected.name }))) return;
    busy = true;
    error = '';
    try {
      await api.del(`/admin/api/tools/profiles/${encodeURIComponent(selected.id)}`);
      selectedId = '';
      await load();
      notice = t('tools.profileDeleted', { name: selected.name });
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  function updateTool(item: ToolItem, state: string): void {
    if (selected?.readonly) return;
    toolDraft = { ...toolDraft, [item.id]: state };
    if (item.type === 'namespace' && state === 'disabled') {
      const next = { ...toolDraft };
      for (const child of namespaceChildren(item.id)) next[child.id] = 'disabled';
      toolDraft = next;
      expandedNamespaces = expandedNamespaces.filter((id) => id !== item.id);
    }
    dirty = true;
  }

  function stateFor(item: ToolItem): string {
    if (item.namespace_id && toolDraft[item.namespace_id] === 'disabled') return 'disabled';
    return toolDraft[item.id] ?? 'disabled';
  }

  function effectiveDisabled(item: ToolItem): boolean {
    return Boolean(item.namespace_id && toolDraft[item.namespace_id] === 'disabled');
  }

  function toggleNamespace(item: ToolItem): void {
    if (stateFor(item) === 'disabled') return;
    expandedNamespaces = expandedNamespaces.includes(item.id)
      ? expandedNamespaces.filter((id) => id !== item.id)
      : [...expandedNamespaces, item.id];
  }

  function namespaceExpanded(item: ToolItem): boolean {
    return stateFor(item) !== 'disabled' && expandedNamespaces.includes(item.id);
  }

  function inputValue(item: ToolItem, input: ProfileInput): string {
    return inputDraft[item.id]?.[input.id] ?? input.default ?? '';
  }

  function setInput(item: ToolItem, input: ProfileInput, value: string): void {
    inputDraft = {
      ...inputDraft,
      [item.id]: { ...(inputDraft[item.id] ?? {}), [input.id]: value },
    };
    dirty = true;
  }

  function inputVisible(item: ToolItem, input: ProfileInput): boolean {
    return !input.ui_hidden && (!input.visible_when?.length || input.visible_when.includes(stateFor(item)));
  }

  function selectOnKeyboard(event: KeyboardEvent, item: ToolItem): void {
    if (event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return;
    event.preventDefault();
    detailId = item.id;
  }

  onMount(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  });
</script>

{#snippet toolCard(item: ToolItem, nested: boolean)}
  <div
    class={`tool-item${nested ? ' nested' : ''} tool-state-${stateFor(item)}`}
    class:selected={detailId === item.id}
    data-tool-id={item.id}
    role="button"
    tabindex="0"
    aria-pressed={detailId === item.id}
    onclick={() => { detailId = item.id; }}
    onkeydown={(event) => selectOnKeyboard(event, item)}
  >
    <div class="tool-name">{item.name ?? item.id}</div>
    <select
      class="tool-state-select"
      aria-label={t('aria.toolState', { name: item.name ?? item.id })}
      disabled={selected?.readonly || effectiveDisabled(item)}
      value={stateFor(item)}
      onclick={(event) => event.stopPropagation()}
      onchange={(event) => updateTool(item, event.currentTarget.value)}
    >
      {#each profilesData.supported_states?.[item.id] ?? ['disabled', 'passthrough', 'modified'] as state}
        <option value={state}>{t(`tools.policy.${state}`)}</option>
      {/each}
    </select>
  </div>
{/snippet}

{#snippet namespaceRow(item: ToolItem)}
  {@const expanded = namespaceExpanded(item)}
  <div class="tool-namespace" data-namespace-id={item.id}>
    <div
      class={`tool-namespace-head tool-state-${stateFor(item)}`}
      class:selected={detailId === item.id}
      data-tool-id={item.id}
      role="button"
      tabindex="0"
      aria-pressed={detailId === item.id}
      onclick={() => { detailId = item.id; }}
      onkeydown={(event) => selectOnKeyboard(event, item)}
    >
      <button
        type="button"
        class="tool-namespace-toggle"
        aria-label={t(expanded ? 'aria.collapseNamespace' : 'aria.expandNamespace', { name: item.name ?? item.id })}
        aria-expanded={expanded}
        aria-controls={`tool-children-${item.id}`}
        disabled={stateFor(item) === 'disabled'}
        onclick={(event) => { event.stopPropagation(); toggleNamespace(item); }}
      >{expanded ? '▾' : '▸'}</button>
      <div class="tool-name">{item.name ?? item.id}</div>
      <div class="tool-badges"><span class="tool-badge kind">{t(`tools.type.${item.type}`)}</span></div>
      <div class="tool-policy">
        <select
          class="tool-state-select"
          aria-label={t('aria.toolState', { name: item.name ?? item.id })}
          disabled={selected?.readonly}
          value={stateFor(item)}
          onclick={(event) => event.stopPropagation()}
          onchange={(event) => updateTool(item, event.currentTarget.value)}
        >
          {#each profilesData.supported_states?.[item.id] ?? ['disabled', 'passthrough', 'modified'] as state}
            <option value={state}>{t(`tools.policy.${state}`)}</option>
          {/each}
        </select>
      </div>
    </div>
    <div
      class="tool-namespace-children"
      id={`tool-children-${item.id}`}
      hidden={!expanded}
    >
      {#each namespaceChildren(item.id) as child (child.id)}
        {@render toolCard(child, true)}
      {/each}
    </div>
  </div>
{/snippet}

<div class="section">
  <div class="section-header"><h2>{t('section.tools')}</h2></div>
  <div class="tools-notice">
    <div>{t('tools.notice')}</div>
    <div style="margin-top:4px">{t('tools.disabledHint')}</div>
  </div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if notice}<div class="toast show" role="status">{notice}</div>{/if}

  {#if loading}
    <div class="tool-catalog-status">{t('tools.loading')}</div>
  {:else if !selected}
    <div class="tool-catalog-status">{t('tools.noProfiles')}</div>
  {:else}
    <div class="tools-meta">
      {t('tools.count',{count:visibleToolCount})}
      {#if (profilesData.references?.[selected.id] ?? []).length}
        · {t('tools.usedBy')} {(profilesData.references?.[selected.id] ?? []).join(', ')}
      {/if}
    </div>
    <div class="tool-profile-toolbar">
      <label for="toolProfileSelect">{t('tools.profile')}</label>
      <select id="toolProfileSelect" value={selectedId} onchange={(event) => selectProfile(event.currentTarget.value)}>
        {#each profilesData.profiles ?? [] as profile}
          <option value={profile.id}>{profile.name}</option>
        {/each}
      </select>
      <button class="btn btn-sm" onclick={() => { cloneName = ''; cloneOpen = true; }}>{t('tools.cloneProfile')}</button>
      <button class="btn btn-sm btn-primary" disabled={busy || !dirty} onclick={() => void saveAs(selected.id)}>{t('tools.saveProfile')}</button>
      <button class="btn btn-sm" disabled={busy || !dirty} onclick={() => selectProfile(selected.id)}>{t('tools.resetProfile')}</button>
      <button class="btn btn-sm btn-danger" disabled={busy || selected.readonly} onclick={() => void remove()}>{t('tools.deleteProfile')}</button>
      {#if dirty}<span class="tool-profile-dirty">{t('tools.unsaved')}</span>{/if}
    </div>
    <div class="tool-profile-protocol-row">
      <span class="tool-profile-protocol-label">{t('tools.apiType')}</span>
      <div class="tool-profile-checkbox-group" role="group" aria-label={t('tools.apiType')}>
        {#each profileApiTypeOptions as option}
          {@const checked = profileApiTypes.includes(option.value)}
          <label class="tool-profile-checkbox">
            <input
              type="checkbox"
              checked={checked}
              disabled={selected.readonly || (checked && profileApiTypes.length === 1)}
              onchange={(event) => toggleProfileApiType(option.value, event.currentTarget.checked)}
            />
            {t(option.labelKey)}
          </label>
        {/each}
      </div>
    </div>

    <div class="tools-toolbar" role="toolbar" aria-label={t('aria.filterToolTypes')}>
      {#each filterOptions as option}
        <button
          class="tool-filter-btn"
          class:active={filter === option.id}
          onclick={() => setFilter(option.id)}
        >{t(option.labelKey)}</button>
      {/each}
    </div>

    <div class="tool-catalog-layout">
      <div class="tool-catalog-groups">
        {#each visibleGroups as group (group.id)}
          <section class="tool-group" data-tool-group={group.id}>
            <div class="tool-group-title">
              <span>{t(`tools.group.${group.id}`)}</span>
              <span class="tool-group-count">{group.items.length}</span>
            </div>
            {#if group.id === 'namespace'}
              <div class="tool-list">
                {#each group.items as item (item.id)}
                  {@render namespaceRow(item)}
                {/each}
              </div>
            {:else}
              <div class="tool-list tool-card-grid">
                {#each group.items as item (item.id)}
                  {@render toolCard(item, false)}
                {/each}
              </div>
            {/if}
          </section>
        {/each}
      </div>

      {#if detail}
        <aside class="tool-detail-panel" aria-label={t('aria.toolDetails')}>
          <div class="tool-detail-header">
            <div class="tool-detail-heading">
              <span class="tool-detail-kicker">{detail.type ?? 'tool'}</span>
              <span class="tool-detail-name">{detail.name ?? detail.id}</span>
            </div>
            <div class="tool-badges"><span class="tool-badge kind">{detail.id}</span></div>
          </div>
          <div class="tool-detail-body">
            {#if detail.description_i18n}<div class="tool-description">{t(detail.description_i18n)}</div>{/if}
            {#if detail.note_i18n && (!detail.note_visible_when?.length || detail.note_visible_when.includes(stateFor(detail)))}
              <div class="tool-description">{t(detail.note_i18n)}</div>
            {/if}
            <div class="tool-policy"><span>{t('tools.detail.policy')}</span><code>{detail.policy_id ?? '-'}</code></div>
            {#if detail.codex_placement}
              <div class="tool-codex-placement">
                <div class="tool-codex-placement-row">
                  <span class="tool-codex-placement-label">{t('tools.detail.normalMode')}</span>
                  <span>{detail.codex_placement.normal_mode_i18n ? t(detail.codex_placement.normal_mode_i18n) : '-'}</span>
                </div>
                <div class="tool-codex-placement-row">
                  <span class="tool-codex-placement-label">{t('tools.detail.codeMode')}</span>
                  <span>{detail.codex_placement.code_mode_i18n ? t(detail.codex_placement.code_mode_i18n) : '-'}</span>
                </div>
              </div>
            {/if}
            <div class="tool-profile-inputs">
              {#each detail.profile_inputs ?? [] as input}
                {#if inputVisible(detail, input)}
                  <div class="tool-profile-input-group">
                    <label class="tool-profile-input-label" for={`tool-${detail.id}-${input.id}`}>{input.label_i18n ? t(input.label_i18n) : input.id}</label>
                    {#if input.type === 'select'}
                      <select
                        id={`tool-${detail.id}-${input.id}`}
                        class="tool-profile-input"
                        disabled={input.readonly}
                        value={inputValue(detail, input)}
                        onchange={(event) => setInput(detail, input, event.currentTarget.value)}
                      >
                        {#each input.options ?? [] as option}<option value={option.value}>{option.label ?? option.value}</option>{/each}
                      </select>
                    {:else if input.type === 'textarea'}
                      <textarea
                        id={`tool-${detail.id}-${input.id}`}
                        class="tool-profile-input tool-profile-textarea"
                        readonly={input.readonly}
                        value={inputValue(detail, input)}
                        oninput={(event) => setInput(detail, input, event.currentTarget.value)}
                      ></textarea>
                    {:else}
                      <input
                        id={`tool-${detail.id}-${input.id}`}
                        class="tool-profile-input"
                        type={input.type === 'password' ? 'password' : 'text'}
                        readonly={input.readonly}
                        value={inputValue(detail, input)}
                        oninput={(event) => setInput(detail, input, event.currentTarget.value)}
                      />
                    {/if}
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        </aside>
      {/if}
    </div>
  {/if}
</div>

<Modal open={cloneOpen} labelledby="tool-clone-title" onclose={() => cloneOpen = false}>
  {#snippet header()}<h3 id="tool-clone-title">{t('tools.cloneTitle')}</h3>{/snippet}
  <div class="form-group">
    <label for="toolProfileCloneName">{t('tools.newProfileName')}</label>
    <input id="toolProfileCloneName" maxlength="128" bind:value={cloneName} placeholder={t('placeholder.toolProfileName')} />
  </div>
  {#snippet actions()}
    <button class="btn" onclick={() => cloneOpen = false}>{t('btn.cancel')}</button>
    <button class="btn btn-primary" disabled={busy || !cloneName.trim()} onclick={() => void createCopy()}>{t('tools.createCopyAction')}</button>
  {/snippet}
</Modal>
