const $ = (id) => document.getElementById(id);

const state = {
  activeJob: null,
  pollTimer: null,
  startedAt: null,
  elapsedTimer: null,
  history: [],
  currentPostRef: null,
  publicationTimer: null,
  integrationsLoaded: false,
  ollamaModels: [],
  selectedModel: null,
  comfyCheckpoints: [],
  selectedCheckpoint: null,
  creationMode: 'ai',
  manualPreviewUrls: [],
};

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2400);
}

function setStatusDot(el, ok) {
  if (!el) return;
  el.classList.remove('ok', 'bad');
  el.classList.add(ok ? 'ok' : 'bad');
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function populateModels(models = [], selected = null) {
  const select = $('modelSelect');
  if (!select) return;

  const unique = [...new Set((models || []).filter(Boolean))];
  const previous = select.value;
  const preferred = selected || state.selectedModel || previous || '';

  select.innerHTML = '';
  if (!unique.length) {
    const option = document.createElement('option');
    option.value = preferred;
    option.textContent = preferred || 'Nenhum modelo encontrado';
    select.appendChild(option);
    select.disabled = true;
    setText('modelCount', '0 modelos');
    setText('modelHelp', 'O Ollama está ativo, mas nenhum modelo foi localizado.');
    return;
  }

  unique.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });

  const chosen = unique.includes(preferred) ? preferred : unique[0];
  select.value = chosen;
  select.disabled = false;
  state.ollamaModels = unique;
  state.selectedModel = chosen;
  setText('modelMeta', chosen);
  setText('modelCount', `${unique.length} modelo${unique.length === 1 ? '' : 's'}`);
  setText('modelHelp', `Modelo ativo: ${chosen}. A escolha fica salva no StudioLab.`);
}

async function loadOllamaModels(showMessage = false) {
  const button = $('refreshModelsBtn');
  if (button) button.disabled = true;
  try {
    const res = await fetch('/api/ollama/models', { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao consultar modelos do Ollama.');
    populateModels(data.models || [], data.selected);
    if (showMessage) showToast(`${data.count || 0} modelo(s) localizado(s)`);
  } catch (err) {
    setText('modelHelp', err.message || 'Falha ao consultar modelos do Ollama.');
    if (showMessage) showToast(err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveSelectedModel() {
  const select = $('modelSelect');
  const model = select?.value || '';
  if (!model) return;

  select.disabled = true;
  try {
    const res = await fetch('/api/settings/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Não foi possível trocar o modelo.');
    state.selectedModel = data.model;
    setText('modelMeta', data.model);
    setText('modelHelp', `Modelo ativo: ${data.model}. A escolha fica salva no StudioLab.`);
    showToast(`Modelo alterado para ${data.model}`);
    refreshStatus();
  } catch (err) {
    showToast(err.message);
    await loadOllamaModels(false);
  } finally {
    select.disabled = false;
  }
}

function populateCheckpoints(checkpoints = [], selected = null) {
  const select = $('checkpointSelect');
  if (!select) return;

  const unique = [...new Set((checkpoints || []).filter(Boolean))];
  const previous = select.value;
  const preferred = selected || state.selectedCheckpoint || previous || '';

  select.innerHTML = '';
  if (!unique.length) {
    const option = document.createElement('option');
    option.value = preferred;
    option.textContent = preferred || 'Nenhum checkpoint encontrado';
    select.appendChild(option);
    select.disabled = true;
    setText('checkpointCount', '0 checkpoints');
    setText('checkpointHelp', 'O ComfyUI está ativo, mas nenhum checkpoint foi localizado.');
    return;
  }

  unique.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });

  const chosen = unique.includes(preferred) ? preferred : unique[0];
  select.value = chosen;
  select.disabled = false;
  state.comfyCheckpoints = unique;
  state.selectedCheckpoint = chosen;
  setText('checkpointMeta', chosen);
  setText('checkpointCount', `${unique.length} checkpoint${unique.length === 1 ? '' : 's'}`);
  setText('checkpointHelp', `Checkpoint ativo: ${chosen}. A escolha fica salva no StudioLab.`);
}

async function loadCheckpoints(showMessage = false) {
  const button = $('refreshCheckpointsBtn');
  if (button) button.disabled = true;
  try {
    const res = await fetch('/api/comfyui/checkpoints', { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao consultar checkpoints do ComfyUI.');
    populateCheckpoints(data.checkpoints || [], data.selected);
    if (showMessage) showToast(`${data.count || 0} checkpoint(s) localizado(s)`);
  } catch (err) {
    setText('checkpointHelp', err.message || 'Falha ao consultar checkpoints do ComfyUI.');
    if (showMessage) showToast(err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveSelectedCheckpoint() {
  const select = $('checkpointSelect');
  const checkpoint = select?.value || '';
  if (!checkpoint) return;

  select.disabled = true;
  try {
    const res = await fetch('/api/settings/checkpoint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ checkpoint }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Não foi possível trocar o checkpoint.');
    state.selectedCheckpoint = data.checkpoint;
    setText('checkpointMeta', data.checkpoint);
    setText('checkpointHelp', `Checkpoint ativo: ${data.checkpoint}. A escolha fica salva no StudioLab.`);
    showToast(`Checkpoint alterado para ${data.checkpoint}`);
    refreshStatus();
  } catch (err) {
    showToast(err.message);
    await loadCheckpoints(false);
  } finally {
    select.disabled = false;
  }
}

async function refreshStatus() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    const data = await res.json();

    if ($('contextAccountHint')) {
      const ctx = data.context?.id || '';
      setText('contextAccountHint', ctx
        ? `Conta atual: @${ctx} · o histórico da IA fica isolado nesta conta.`
        : 'Conta atual sem Instagram identificado · use o briefing para definir o contexto.');
    }

    setStatusDot($('ollamaDot'), !!data.ollama?.ok);
    setText('ollamaText', data.ollama?.ok
      ? (data.ollama.model_ok ? `${data.ollama.model} pronto · ${data.ollama.count || 0} instalado(s)` : `Servidor ativo · modelo não localizado`)
      : 'Indisponível');
    if (data.ollama?.ok) populateModels(data.ollama.models || [], data.ollama.model);

    setStatusDot($('comfyDot'), !!data.comfyui?.ok);
    if (data.comfyui?.ok) {
      const cp = data.comfyui.checkpoints?.length || 0;
      const device = data.comfyui.device || 'ativo';
      setText('comfyText', `${device} · ${cp} checkpoint${cp === 1 ? '' : 's'}`);
      populateCheckpoints(data.comfyui.checkpoints || [], data.comfyui.selected_checkpoint || data.comfyui.preferred_checkpoint);
    } else {
      setText('comfyText', 'Indisponível');
    }

    const tg = data.integrations?.telegram || {};
    setStatusDot($('telegramDot'), !!tg.configured);
    setText('telegramText', tg.configured ? (tg.bot_name ? `@${tg.bot_name.replace(/^@/, '')}` : 'Configurado') : 'Não configurado');

    const ig = data.integrations?.instagram || {};
    setStatusDot($('instagramDot'), !!ig.configured);
    setText('instagramText', ig.configured ? `@${ig.username}` : 'Não configurado');
    setText('activeClientText', data.client_active || (ig.username ? `@${ig.username}` : 'Nenhum Instagram ativo'));

    if (data.active_job && !state.activeJob) {
      state.activeJob = data.active_job;
      startPolling(data.active_job);
    }
  } catch (err) {
    setStatusDot($('ollamaDot'), false);
    setStatusDot($('comfyDot'), false);
    setStatusDot($('telegramDot'), false);
    setStatusDot($('instagramDot'), false);
    setText('ollamaText', 'Falha ao consultar');
    setText('comfyText', 'Falha ao consultar');
  }
}

function updateElapsed() {
  if (!state.startedAt) return;
  const sec = Math.floor((Date.now() - state.startedAt) / 1000);
  const mm = String(Math.floor(sec / 60)).padStart(2, '0');
  const ss = String(sec % 60).padStart(2, '0');
  setText('elapsedTime', `${mm}:${ss}`);
}

function startElapsed() {
  state.startedAt = Date.now();
  clearInterval(state.elapsedTimer);
  updateElapsed();
  state.elapsedTimer = setInterval(updateElapsed, 1000);
}

function stopElapsed() {
  clearInterval(state.elapsedTimer);
  state.elapsedTimer = null;
}

function showProgress(job) {
  $('progressPanel').classList.remove('hidden');
  $('errorPanel').classList.add('hidden');
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)));
  setText('progressPercent', `${pct}%`);
  $('progressFill').style.width = `${pct}%`;
  setText('progressStage', job.stage || 'PROCESSANDO');
  setText('progressMessage', job.message || 'Processando');
}

function setGenerating(active) {
  const btn = $('generateBtn');
  btn.disabled = active;
  $('previewLoading').classList.toggle('hidden', !active);
  if (active) {
    $('previewEmpty').classList.add('hidden');
    startElapsed();
  } else {
    stopElapsed();
  }
}

function publicationInfo(publication = {}) {
  const status = publication.status || 'rascunho';
  const map = {
    rascunho: ['Rascunho', 'Aguardando envio para validação.', 'neutral'],
    aguardando_aprovacao: ['Aguardando aprovação', 'O post foi enviado ao Telegram.', 'pending'],
    aprovado: ['Aprovado', 'Validação concluída. Aguardando publicação.', 'ok'],
    rejeitado: ['Reprovado', 'O post foi reprovado no Telegram e não será publicado.', 'bad'],
    publicando: ['Publicando', 'Enviando o post para o Instagram…', 'pending'],
    publicado: ['Publicado', 'Publicação concluída no Instagram.', 'ok'],
    erro_telegram: ['Falha no Telegram', publication.error || 'Não foi possível enviar para validação.', 'bad'],
    erro_publicacao: ['Erro na publicação', publication.error || 'A publicação no Instagram falhou.', 'bad'],
  };
  return map[status] || [status, publication.error || '', 'neutral'];
}

function renderPublication(publication = {}) {
  const strip = $('publicationStrip');
  if (!strip) return;
  strip.classList.remove('hidden');
  const [label, defaultDetail, tone] = publicationInfo(publication);
  setText('publicationStatus', label);
  setText('publicationDetail', publication.validated_by ? `${defaultDetail} Validado por ${publication.validated_by}.` : defaultDetail);

  const dot = $('publicationDot');
  dot.className = `publication-dot ${tone}`;

  const status = publication.status || 'rascunho';
  const sendBtn = $('sendReviewBtn');
  const publishBtn = $('publishRetryBtn');
  const openBtn = $('instagramOpenBtn');

  sendBtn.classList.toggle('hidden', !['rascunho', 'erro_telegram', 'rejeitado'].includes(status));
  publishBtn.classList.toggle('hidden', !['aprovado', 'erro_publicacao'].includes(status));

  if (status === 'publicado' && publication.instagram_url) {
    openBtn.href = publication.instagram_url;
    openBtn.classList.remove('hidden');
  } else {
    openBtn.classList.add('hidden');
    openBtn.href = '#';
  }
}

function renderResult(result) {
  if (!result) return;
  const img = $('cardPreview');
  if (result.card_url) {
    img.src = `${result.card_url}?t=${Date.now()}`;
    img.classList.remove('hidden');
    $('previewEmpty').classList.add('hidden');
  }

  state.currentPostRef = result.post_ref || state.currentPostRef;
  setText('templatePill', templateName(result.template));
  setText('resultBadge', result.badge || 'CONTEÚDO IA');
  setText('resultTopic', result.topic || 'Conteúdo');
  setText('resultTitle', result.title || '');
  setText('resultBody', result.body || '');
  setText('resultHighlight', result.highlight || '');
  $('resultMeta').classList.remove('hidden');

  setText('captionText', result.caption || '');
  $('captionCard').classList.remove('hidden');
  renderPublication(result.publication || { status: 'rascunho' });

  const note = $('generationNote');
  if (result.comfyui_warning) {
    note.textContent = `Observação: ${result.comfyui_warning}`;
    note.classList.remove('hidden');
  } else {
    note.classList.add('hidden');
  }
}

function templateName(value) {
  const map = {
    auto: 'Automático',
    classic_left: 'Clássico editorial',
    spotlight_card: 'Spotlight premium',
    modern_split: 'Split moderno',
    ai_dynamic: 'Dinâmico por IA',
    manual_upload: 'Upload manual',
  };
  return map[value] || value || 'Automático';
}

async function pollJob(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`, { cache: 'no-store' });
    const job = await res.json();
    if (!res.ok) throw new Error(job.error || 'Falha ao consultar geração');

    showProgress(job);

    if (job.status === 'done') {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.activeJob = null;
      setGenerating(false);
      renderResult(job.result);
      setText('progressHint', job.result?.publication?.status === 'aguardando_aprovacao'
        ? 'Geração concluída e enviada ao Telegram para aprovação.'
        : 'Geração concluída e salva no histórico.');
      showToast('Post gerado com sucesso');
      loadHistory();
      refreshStatus();
      return;
    }

    if (job.status === 'error') {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.activeJob = null;
      setGenerating(false);
      const error = $('errorPanel');
      error.textContent = job.error || job.message || 'Erro na geração.';
      error.classList.remove('hidden');
      setText('progressHint', 'A geração foi interrompida.');
      refreshStatus();
    }
  } catch (err) {
    console.error(err);
  }
}

function startPolling(jobId) {
  clearInterval(state.pollTimer);
  state.activeJob = jobId;
  setGenerating(true);
  $('progressPanel').classList.remove('hidden');
  setText('progressHint', 'A geração por CPU pode levar alguns minutos.');
  pollJob(jobId);
  state.pollTimer = setInterval(() => pollJob(jobId), 1200);
}

function setCreationMode(mode) {
  const manual = mode === 'manual';
  state.creationMode = manual ? 'manual' : 'ai';
  $('aiComposer').classList.toggle('hidden', manual);
  $('manualComposer').classList.toggle('hidden', !manual);
  $('modeAiBtn').classList.toggle('active', !manual);
  $('modeManualBtn').classList.toggle('active', manual);
  setText('templatePill', manual ? 'Upload manual' : ($('templatePill').textContent || 'Aguardando geração'));
}

function clearManualPreviewUrls() {
  state.manualPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.manualPreviewUrls = [];
}

function renderManualFiles() {
  const input = $('manualImages');
  const thumbs = $('manualThumbs');
  if (!input || !thumbs) return;
  clearManualPreviewUrls();
  thumbs.innerHTML = '';
  const files = [...(input.files || [])];
  setText('manualImageCount', `${files.length}/10`);
  if (files.length > 10) {
    showToast('Selecione no máximo 10 imagens');
    input.value = '';
    setText('manualImageCount', '0/10');
    return;
  }
  files.forEach((file, index) => {
    const url = URL.createObjectURL(file);
    state.manualPreviewUrls.push(url);
    const item = document.createElement('div');
    item.className = 'manual-thumb';
    item.innerHTML = `<img src="${url}" alt="Imagem ${index + 1}"><span>${index + 1}</span>`;
    thumbs.appendChild(item);
  });
}

async function submitManualPost() {
  const input = $('manualImages');
  const files = [...(input?.files || [])];
  const caption = $('manualCaption').value.trim();
  const title = $('manualTitle').value.trim();
  if (!files.length) return showToast('Selecione pelo menos uma imagem');
  if (files.length > 10) return showToast('Envie no máximo 10 imagens');
  if (!caption) return showToast('Digite a descrição/legenda');

  const form = new FormData();
  files.forEach((file) => form.append('images', file, file.name));
  form.append('caption', caption);
  form.append('title', title);

  const btn = $('manualPostBtn');
  const progress = $('manualUploadProgress');
  btn.disabled = true;
  progress.classList.remove('hidden');
  $('errorPanel').classList.add('hidden');
  try {
    const res = await fetch('/api/manual-post', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Não foi possível preparar a publicação.');
    renderResult(data.result);
    showToast(files.length > 1 ? 'Carrossel preparado com sucesso' : 'Post manual preparado com sucesso');
    input.value = '';
    $('manualCaption').value = '';
    $('manualTitle').value = '';
    setText('manualCaptionCount', '0');
    renderManualFiles();
    await loadHistory();
    refreshStatus();
  } catch (err) {
    const error = $('errorPanel');
    error.textContent = err.message;
    error.classList.remove('hidden');
    showToast(err.message);
  } finally {
    btn.disabled = false;
    progress.classList.add('hidden');
  }
}

async function generatePost() {
  const orientation = $('orientation').value.trim();
  const template = $('template').value;
  const useComfy = $('useComfy').checked;
  const model = $('modelSelect')?.value || state.selectedModel || '';
  const checkpoint = $('checkpointSelect')?.value || state.selectedCheckpoint || '';

  $('errorPanel').classList.add('hidden');
  $('progressFill').style.width = '0%';
  setText('progressPercent', '0%');
  setText('progressStage', 'FILA');
  setText('progressMessage', 'Iniciando agente');
  $('progressPanel').classList.remove('hidden');
  setGenerating(true);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ orientation, template, use_comfyui: useComfy, model, checkpoint }),
    });
    const data = await res.json();

    if (res.status === 409 && data.job_id) {
      showToast('Já existe uma geração em andamento');
      startPolling(data.job_id);
      return;
    }

    if (!res.ok) throw new Error(data.error || 'Não foi possível iniciar a geração.');
    startPolling(data.job_id);
  } catch (err) {
    setGenerating(false);
    const error = $('errorPanel');
    error.textContent = err.message;
    error.classList.remove('hidden');
  }
}

function formatDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d);
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
}

function publicationBadge(publication = {}) {
  const status = publication.status || 'rascunho';
  const [label, , tone] = publicationInfo(publication);
  return `<span class="history-publication ${tone}">${escapeHtml(label)}</span>`;
}

function renderHistory(items) {
  state.history = items;
  const grid = $('historyGrid');
  const empty = $('historyEmpty');
  grid.innerHTML = '';

  if (!items.length) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  items.forEach((item, index) => {
    const status = item.publication?.status || 'rascunho';
    const canReview = ['rascunho', 'erro_telegram', 'rejeitado'].includes(status);
    const canPublish = ['aprovado', 'erro_publicacao'].includes(status);
    const card = document.createElement('article');
    card.className = 'history-card';
    card.innerHTML = `
      <div class="history-thumb" data-open="${index}">
        ${item.card_url ? `<img src="${escapeHtml(item.card_url)}" alt="${escapeHtml(item.title || 'Card')}">` : ''}
      </div>
      <div class="history-body">
        <div class="history-kicker"><span>${escapeHtml(item.badge || 'POST')}</span><span>${escapeHtml(formatDate(item.created_at))}</span></div>
        ${item.source === 'manual_upload' ? `<div class="manual-history-meta">Upload manual · ${item.media_count || 1} ${Number(item.media_count || 1) > 1 ? 'imagens' : 'imagem'}</div>` : ''}
        <div class="history-status-row">${publicationBadge(item.publication)}</div>
        <h3>${escapeHtml(item.title || 'Sem título')}</h3>
        <p>${escapeHtml(item.body || '')}</p>
        <div class="history-actions">
          <button data-open="${index}">Abrir</button>
          <button data-copy="${index}">Copiar legenda</button>
          ${canReview ? `<button class="accent-action" data-review="${index}">Telegram</button>` : ''}
          ${canPublish ? `<button class="accent-action" data-publish="${index}">Publicar</button>` : ''}
        </div>
      </div>`;
    grid.appendChild(card);
  });

  grid.querySelectorAll('[data-open]').forEach((el) => {
    el.addEventListener('click', () => openHistory(Number(el.dataset.open)));
  });
  grid.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', async () => {
      const item = state.history[Number(el.dataset.copy)];
      await navigator.clipboard.writeText(item.caption || '');
      showToast('Legenda copiada');
    });
  });
  grid.querySelectorAll('[data-review]').forEach((el) => {
    el.addEventListener('click', () => sendForReview(state.history[Number(el.dataset.review)]?.post_ref));
  });
  grid.querySelectorAll('[data-publish]').forEach((el) => {
    el.addEventListener('click', () => publishPost(state.history[Number(el.dataset.publish)]?.post_ref));
  });
}

function openHistory(index) {
  const item = state.history[index];
  if (!item) return;
  renderResult({
    post_ref: item.post_ref,
    topic: item.topic,
    badge: item.badge,
    title: item.title,
    body: item.body,
    highlight: item.highlight,
    caption: item.caption,
    template: item.template,
    icon: item.icon,
    checkpoint: item.checkpoint,
    publication: item.publication,
    card_url: item.card_url,
    background_url: item.background_url,
    source: item.source,
    media_count: item.media_count,
  });
  switchSection('studio');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadHistory() {
  try {
    const res = await fetch('/api/history?limit=18', { cache: 'no-store' });
    const data = await res.json();
    const items = data.items || [];
    renderHistory(items);
    if (items.length && $('cardPreview').classList.contains('hidden')) {
      renderResult(items[0]);
    }
    if (state.currentPostRef) {
      const current = items.find((item) => item.post_ref === state.currentPostRef);
      if (current) renderPublication(current.publication || {});
    }
  } catch (err) {
    console.error(err);
  }
}

async function refreshCurrentPublication() {
  if (!state.currentPostRef) return;
  try {
    const res = await fetch(`/api/posts/${state.currentPostRef}/status`, { cache: 'no-store' });
    const data = await res.json();
    if (res.ok) renderPublication(data.publication || {});
  } catch (_) {}
}

async function sendForReview(postRef = state.currentPostRef) {
  if (!postRef) return showToast('Selecione um post primeiro');
  try {
    const res = await fetch(`/api/posts/${postRef}/send-review`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao enviar ao Telegram.');
    renderPublication(data.publication || {});
    showToast('Post enviado para validação no Telegram');
    loadHistory();
  } catch (err) {
    showToast(err.message);
  }
}

async function publishPost(postRef = state.currentPostRef) {
  if (!postRef) return showToast('Selecione um post primeiro');
  try {
    const res = await fetch(`/api/posts/${postRef}/publish`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao iniciar publicação.');
    renderPublication(data.publication || { status: 'publicando' });
    showToast('Publicação iniciada');
    setTimeout(refreshCurrentPublication, 2500);
  } catch (err) {
    showToast(err.message);
  }
}

function switchSection(section) {
  document.querySelectorAll('.nav-item').forEach((btn) => btn.classList.toggle('active', btn.dataset.section === section));
  $('studioSection').classList.toggle('active', section === 'studio');
  $('historySection').classList.toggle('active', section === 'history');
  $('integrationsSection').classList.toggle('active', section === 'integrations');
  if (section === 'history') loadHistory();
  if (section === 'integrations') loadIntegrations();
}

async function loadIntegrations() {
  try {
    const res = await fetch('/api/integrations/config', { cache: 'no-store' });
    const cfg = await res.json();
    const tg = cfg.telegram || {};
    const ig = cfg.instagram || {};

    $('telegramEnabled').checked = !!tg.enabled;
    $('telegramChatId').value = tg.chat_id || '';
    $('telegramAllowedUsers').value = (tg.allowed_user_ids || []).join(', ');
    $('telegramAutoSend').checked = tg.auto_send_review !== false;
    $('telegramToken').value = '';
    $('telegramToken').placeholder = tg.token_saved ? `Token salvo (${tg.token_hint || '••••'}) · deixe vazio para manter` : 'Cole o token criado no BotFather';
    const tgState = tg.configured ? 'Ativo' : (tg.enabled ? 'Ativo · falta configurar' : 'Desativado');
    setText('telegramConfigState', tgState);
    $('telegramConfigState').classList.toggle('ready', !!tg.configured);

    $('instagramEnabled').checked = !!ig.enabled;
    $('instagramUsername').value = ig.username || '';
    $('instagramPassword').value = '';
    $('instagramPassword').placeholder = ig.password_saved ? 'Senha já salva · deixe vazio para manter' : 'Digite a senha da conta';
    $('instagramAutoPublish').checked = ig.auto_publish_on_approval !== false;
    setText('instagramActiveAccount', ig.username ? `@${ig.username}${ig.session_saved ? ' · sessão ativa' : ''}` : 'Nenhuma conta conectada');
    setText('activeClientText', ig.username ? `@${ig.username}` : 'Nenhum Instagram ativo');
    const igState = ig.configured
      ? (ig.session_saved ? 'Ativo · sessão salva' : 'Ativo')
      : (ig.enabled ? 'Ativo · falta configurar' : 'Desativado');
    setText('instagramConfigState', igState);
    $('instagramConfigState').classList.toggle('ready', !!ig.configured);
    state.integrationsLoaded = true;
  } catch (err) {
    showToast('Falha ao carregar integrações');
  }
}

function integrationPayload() {
  return {
    telegram: {
      enabled: $('telegramEnabled').checked,
      bot_token: $('telegramToken').value.trim(),
      chat_id: $('telegramChatId').value.trim(),
      allowed_user_ids: $('telegramAllowedUsers').value.trim(),
      auto_send_review: $('telegramAutoSend').checked,
    },
    instagram: {
      enabled: $('instagramEnabled').checked,
      username: $('instagramUsername').value.trim(),
      password: $('instagramPassword').value,
      auto_publish_on_approval: $('instagramAutoPublish').checked,
    },
  };
}

async function saveIntegrations(showMessage = true) {
  const res = await fetch('/api/integrations/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(integrationPayload()),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Não foi possível salvar as integrações.');
  if (showMessage) showToast('Configurações salvas');
  await loadIntegrations();
  refreshStatus();
  return data;
}

async function persistIntegrationToggle(element, enabledMessage, disabledMessage) {
  const line = element.closest('.toggle-line');
  if (line) line.classList.add('integration-saving');
  try {
    await saveIntegrations(false);
    showToast(element.checked ? enabledMessage : disabledMessage);
  } catch (err) {
    element.checked = !element.checked;
    showToast(err.message || 'Não foi possível salvar a configuração.');
    await loadIntegrations();
  } finally {
    if (line) line.classList.remove('integration-saving');
  }
}

async function testTelegram() {
  const result = $('telegramTestResult');
  result.className = 'inline-result';
  result.textContent = 'Testando…';
  try {
    await saveIntegrations(false);
    const res = await fetch('/api/integrations/test/telegram', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha no Telegram.');
    result.className = 'inline-result ok';
    result.textContent = data.bot ? `Conectado · @${String(data.bot).replace(/^@/, '')}` : 'Conectado';
    showToast('Mensagem de teste enviada ao Telegram');
    refreshStatus();
  } catch (err) {
    result.className = 'inline-result bad';
    result.textContent = err.message;
  }
}

async function testInstagram() {
  const result = $('instagramTestResult');
  result.className = 'inline-result';
  result.textContent = 'Validando sessão…';
  try {
    await saveIntegrations(false);
    const res = await fetch('/api/integrations/test/instagram', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha no login do Instagram.');
    result.className = 'inline-result ok';
    result.textContent = `Login válido · @${data.username}`;
    showToast('Sessão do Instagram validada');
    await loadIntegrations();
    refreshStatus();
  } catch (err) {
    result.className = 'inline-result bad';
    result.textContent = err.message;
  }
}

async function switchInstagramAccount() {
  const result = $('instagramTestResult');
  const username = $('instagramUsername').value.trim().replace(/^@/, '');
  const password = $('instagramPassword').value;

  if (!username) {
    result.className = 'inline-result bad';
    result.textContent = 'Informe o usuário da nova conta.';
    $('instagramUsername').focus();
    return;
  }
  if (!password) {
    result.className = 'inline-result bad';
    result.textContent = 'Informe a senha da nova conta para validar a troca.';
    $('instagramPassword').focus();
    return;
  }

  const atual = ($('instagramActiveAccount').textContent || '').split(' · ')[0];
  if (!window.confirm(`Trocar ${atual || 'a conta atual'} por @${username}? A conta anterior será mantida se o novo login falhar.`)) return;

  result.className = 'inline-result';
  result.textContent = `Conectando @${username}…`;
  $('switchInstagram').disabled = true;
  $('testInstagram').disabled = true;
  try {
    const res = await fetch('/api/integrations/switch/instagram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password,
        enabled: true,
        auto_publish_on_approval: $('instagramAutoPublish').checked,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Não foi possível trocar a conta do Instagram.');

    result.className = 'inline-result ok';
    result.textContent = `Conta ativa · @${data.username}`;
    $('instagramPassword').value = '';
    showToast(`Instagram alterado para @${data.username}`);
    await loadIntegrations();
    await refreshStatus();
  } catch (err) {
    result.className = 'inline-result bad';
    result.textContent = err.message;
    showToast('A conta anterior foi preservada');
    await loadIntegrations();
    await refreshStatus();
  } finally {
    $('switchInstagram').disabled = false;
    $('testInstagram').disabled = false;
  }
}

function bindEvents() {
  $('generateBtn').addEventListener('click', generatePost);
  $('modeAiBtn').addEventListener('click', () => setCreationMode('ai'));
  $('modeManualBtn').addEventListener('click', () => setCreationMode('manual'));
  $('manualImages').addEventListener('change', renderManualFiles);
  $('manualCaption').addEventListener('input', () => setText('manualCaptionCount', $('manualCaption').value.length));
  $('manualPostBtn').addEventListener('click', submitManualPost);
  $('modelSelect').addEventListener('change', saveSelectedModel);
  $('refreshModelsBtn').addEventListener('click', () => loadOllamaModels(true));
  $('checkpointSelect').addEventListener('change', saveSelectedCheckpoint);
  $('refreshCheckpointsBtn').addEventListener('click', () => loadCheckpoints(true));
  $('refreshStatus').addEventListener('click', () => { refreshStatus(); showToast('Status atualizado'); });
  $('refreshHistory').addEventListener('click', loadHistory);
  $('orientation').addEventListener('input', () => setText('orientationCount', $('orientation').value.length));
  $('copyCaption').addEventListener('click', async () => {
    await navigator.clipboard.writeText($('captionText').textContent || '');
    showToast('Legenda copiada');
  });
  $('sendReviewBtn').addEventListener('click', () => sendForReview());
  $('publishRetryBtn').addEventListener('click', () => publishPost());
  $('saveIntegrations').addEventListener('click', async () => {
    try { await saveIntegrations(true); } catch (err) { showToast(err.message); }
  });
  $('testTelegram').addEventListener('click', testTelegram);
  $('testInstagram').addEventListener('click', testInstagram);
  $('switchInstagram').addEventListener('click', switchInstagramAccount);

  $('telegramEnabled').addEventListener('change', (event) => {
    persistIntegrationToggle(
      event.currentTarget,
      'Validação via Telegram ativada',
      'Validação via Telegram desativada'
    );
  });
  $('instagramEnabled').addEventListener('change', (event) => {
    persistIntegrationToggle(
      event.currentTarget,
      'Publicação no Instagram ativada',
      'Publicação no Instagram desativada'
    );
  });
  $('telegramAutoSend').addEventListener('change', (event) => {
    persistIntegrationToggle(
      event.currentTarget,
      'Envio automático ao Telegram ativado',
      'Envio automático ao Telegram desativado'
    );
  });
  $('instagramAutoPublish').addEventListener('change', (event) => {
    persistIntegrationToggle(
      event.currentTarget,
      'Publicação após aprovação ativada',
      'Publicação após aprovação desativada'
    );
  });

  document.querySelectorAll('.nav-item').forEach((btn) => btn.addEventListener('click', () => switchSection(btn.dataset.section)));
}

bindEvents();
loadOllamaModels(false);
loadCheckpoints(false);
refreshStatus();
loadHistory();
loadIntegrations();
setInterval(refreshStatus, 15000);
state.publicationTimer = setInterval(refreshCurrentPublication, 8000);
