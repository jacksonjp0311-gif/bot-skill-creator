'use strict';
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = {token:'', project:null, projects:[], provider:{connected:false}, file:'SKILL.md', busy:false, reviewed:null, providerPick:null, localModels:[], holdLocal:false, savedKeys:[], localSaved:null, pending:'', phaseLabel:'', revealReply:false, clarifyDismissed:false, harness:{accepted:false}, harnessHomes:[], harnessPick:'', harnessAgreed:'', harnessPrompted:false, untilClose:false, clientId:'', holdingStudio:false};
let phaseWatch = 0;
const PROVIDERS = [
  {id:'openai', name:'ChatGPT', maker:'OpenAI', mark:'GPT', color:'#0f766e', blurb:'Current ChatGPT chat models. The field still accepts an exact model ID.', base:'https://api.openai.com/v1', token:'max_completion_tokens', json:true, local:false, models:[
    'gpt-6-astra','gpt-6.1-sol','gpt-6-sol','gpt-6-luna',
    'gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna',
    'gpt-5.5','gpt-5.5-pro','gpt-5.4','gpt-5.4-pro','gpt-5.4-mini',
    'gpt-5.2','gpt-5.2-pro','gpt-5','gpt-5-mini','gpt-5-nano','gpt-5-pro',
    'o3','o3-pro','gpt-4.1','gpt-4.1-mini','gpt-4o','gpt-4o-mini',
    'gpt-oss-120b','gpt-oss-20b'
  ]},
  {id:'grok', name:'Grok', maker:'xAI', mark:'G', color:'#111827', blurb:'Grok models on the xAI chat completions endpoint.', base:'https://api.x.ai/v1', token:'max_completion_tokens', json:true, local:false, models:['grok-4.7','grok-4.6']},
  {id:'claude', name:'Claude', maker:'Anthropic', mark:'C', color:'#c45c26', blurb:'Claude through Anthropic’s compatible chat endpoint. JSON mode starts off.', base:'https://api.anthropic.com/v1', token:'max_tokens', json:false, local:false, models:['claude-sonnet-4-5','claude-opus-4-1']},
  {id:'openrouter', name:'OpenRouter', maker:'Router', mark:'OR', color:'#5b4cdb', blurb:'One key for many models. Use the provider/model ID.', base:'https://openrouter.ai/api/v1', token:'max_tokens', json:false, local:false, models:['openai/gpt-4.1','x-ai/grok-4','anthropic/claude-sonnet-4.5','google/gemini-2.5-pro']},
  {id:'gemini', name:'Gemini', maker:'Google', mark:'Ge', color:'#1a73c7', blurb:'Gemini through Google’s compatible chat endpoint.', base:'https://generativelanguage.googleapis.com/v1beta/openai', token:'max_tokens', json:true, local:false, models:['gemini-2.5-pro','gemini-2.5-flash']},
  {id:'mistral', name:'Mistral', maker:'Mistral', mark:'M', color:'#e85d04', blurb:'Mistral chat models.', base:'https://api.mistral.ai/v1', token:'max_tokens', json:true, local:false, models:['mistral-large-latest','mistral-small-latest']},
  {id:'groq', name:'Groq', maker:'Groq', mark:'Q', color:'#e11d48', blurb:'Fast open models on Groq’s compatible endpoint.', base:'https://api.groq.com/openai/v1', token:'max_tokens', json:false, local:false, models:['llama-3.3-70b-versatile']},
  {id:'local', name:'This machine', maker:'Ollama', mark:'⌂', color:'#469478', blurb:'Reads models from Ollama on this machine and fills the endpoint. No API key.', base:'http://127.0.0.1:11434/v1', token:'max_tokens', json:false, local:true, models:[]},
  {id:'custom', name:'Other', maker:'Custom', mark:'+', color:'#6752d1', blurb:'Any other chat-completions endpoint. Paste its base URL and model ID.', base:'', token:'max_completion_tokens', json:true, local:false, models:[]}
];
function sameBase(a, b) { return String(a || '').replace(/\/$/, '') === String(b || '').replace(/\/$/, ''); }
let toastTimer;
function savedTheme() {
  try {
    const saved = localStorage.getItem('bsc-theme');
    if (saved === 'dark' || saved === 'light') return saved;
  } catch (error) {}
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function applyTheme(theme) {
  const next = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  const button = $('#theme-toggle');
  if (!button) return;
  const dark = next === 'dark';
  button.textContent = dark ? 'Light' : 'Dark';
  button.setAttribute('aria-pressed', dark ? 'true' : 'false');
  button.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
}
function nonempty(value) {
  return Array.isArray(value) ? value.some(item => String(item).trim()) : Boolean(value && String(value).trim());
}
function renderChecks(plan) {
  const ready = [
    nonempty(plan?.goal),
    nonempty(plan?.steps) || nonempty(plan?.inputs),
    nonempty(plan?.constraints),
    nonempty(plan?.success_criteria)
  ];
  $$('#checks .check-dot').forEach((dot, index) => {
    const ok = Boolean(ready[index]);
    dot.textContent = ok ? '✓' : '○';
    dot.classList.toggle('pending', !ok);
  });
}
function fitComposer() {
  const field = $('#message-input');
  field.style.height = 'auto';
  field.style.height = Math.min(field.scrollHeight, 112) + 'px';
}
function node(tag, cls, content) { const el = document.createElement(tag); if(cls) el.className=cls; if(content!==undefined) el.textContent=content; return el; }
function toast(message) { const el=$('#toast'); el.textContent=message; el.hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>{el.hidden=true;},5500); }
async function api(path, data) {
  const options={headers:{'X-BSC-Token':state.token}};
  if(data!==undefined) {options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
  const response=await fetch(path,options);
  const result=await response.json();
  if(!response.ok) throw new Error(result.error||'The request could not be completed.');
  return result;
}
async function run(fn) {
  if(state.busy) {toast('Finish the current request before changing this draft.');return;}
  state.busy=true; document.body.classList.add('is-busy'); $('#send').disabled=true;
  $('#status-text').textContent=state.pending?workingCopy():'Working on this request…';
  let failed=false;
  try {await fn();}
  catch(error) {failed=true; toast(error.message); $('#status-text').textContent='Request stopped · Draft retained';}
  finally {
    state.busy=false; document.body.classList.remove('is-busy'); $('#send').disabled=false;
    if(!failed) { renderStatus(); maybeAsk(state.project); }
    else {$('#export').disabled=!state.project?.validation?.ok; $('#edit-plan').disabled=!state.project?.plan;}
  }
}
function renderStatus() {
  const p=state.project;
  $('#export').disabled=!p?.validation?.ok||state.busy;
  $('#edit-plan').disabled=!p?.plan||state.busy;
  if(state.busy) return;
  $('#status-text').textContent=p?.plan?`Revision ${p.revision} · Saved locally · Static checks only`:'Ready to create';
}
function view(name) {
  $$('.view').forEach(v=>{v.hidden=v.id!==`${name}-view`;});
  $$('.nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));
  $('#crumb').textContent=({studio:'Skill studio',apis:'API connections',harness:'Harness',library:'My skills',algorithm:'The algorithm'})[name];
  if(name==='apis') { renderProviderCards(); renderAPI(); }
  if(name==='harness') renderHarness(false);
  if(name==='library') renderLibrary();
  if(name==='algorithm') calculate();
}
const SCAN_LINES = ['Reading this machine…', 'Checking Hermes markers…', 'Leaving secrets closed…'];
let scanTimer = 0;
let harnessFindBusy = false;
function startScan(title, copy) {
  $('#harness-dialog-title').textContent = title;
  $('#harness-dialog-copy').textContent = copy;
  $('#harness-scan').hidden = false;
  $('#harness-results').hidden = true;
  let step = 0;
  $('#harness-scan-caption').textContent = SCAN_LINES[0];
  clearInterval(scanTimer);
  scanTimer = setInterval(() => {
    step = (step + 1) % SCAN_LINES.length;
    $('#harness-scan-caption').textContent = SCAN_LINES[step];
  }, 900);
}
function stopScan() {
  clearInterval(scanTimer);
  scanTimer = 0;
}
function dwell(started, minimum = 850) {
  const remaining = minimum - (performance.now() - started);
  if (remaining <= 0) return Promise.resolve();
  return new Promise(resolve => setTimeout(resolve, remaining));
}
function pathKey(value) {
  return String(value || '').replace(/[\\/]+$/, '').replace(/\\/g, '/').toLowerCase();
}
function renderHarnessChoices() {
  const host = $('#harness-choices');
  host.replaceChildren();
  const homes = state.harnessHomes || [];
  if (!state.harnessPick && homes[0]) state.harnessPick = homes[0].path;
  homes.forEach(home => {
    const card = node('button', 'harness-choice' + (home.path === state.harnessPick ? ' selected' : ''));
    card.type = 'button';
    const memory = home.memory_files && home.memory_files.length ? home.memory_files.length + ' memory files' : 'no memory files';
    card.append(node('strong', '', home.name || 'Hermes'));
    card.append(node('small', '', home.path));
    card.append(node('small', '', `${home.markers.join(' · ')} · ${home.skill_count} skills · ${memory} · ${home.tool_count} tools`));
    card.addEventListener('click', () => {
      state.harnessPick = home.path;
      state.harnessAgreed = '';
      $('#harness-agree').disabled = false;
      $('#harness-accept').disabled = true;
      renderHarnessChoices();
    });
    host.append(card);
  });
  $('#harness-agree').disabled = !state.harnessPick && !$('#harness-path').value.trim();
  $('#harness-accept').disabled = !state.harnessAgreed;
}
function renderDirectory(tree) {
  const host = $('#harness-directory');
  host.replaceChildren();
  (tree && tree.children || []).forEach(group => {
    const block = node('div', 'dir-block');
    block.append(node('strong', '', group.name.toUpperCase()));
    const rows = group.children || [];
    if (!rows.length) block.append(node('span', 'dir-empty', 'None found'));
    rows.forEach(row => block.append(node('span', 'dir-row', row.name)));
    host.append(block);
  });
}
function renderNexus(profile, reveal) {
  const board = $('#nexus-board');
  board.replaceChildren();
  const nodes = profile.nexus && profile.nexus.nodes || [];
  const edges = profile.nexus && profile.nexus.edges || [];
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 640 460');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Nexus of the accepted harness');
  const hub = nodes.find(item => item.id === 'harness') || {id:'harness', label:'Hermes'};
  const rest = nodes.filter(item => item.id !== 'harness');
  const placed = new Map([[hub.id, {x:320, y:214, r:26}]]);
  rest.forEach((item, index) => {
    const angle = (-Math.PI / 2) + (index / Math.max(rest.length, 1)) * Math.PI * 2;
    const rx = rest.length > 10 ? 250 : 210;
    placed.set(item.id, {x:320 + Math.cos(angle) * rx, y:214 + Math.sin(angle) * 150, r:item.kind === 'limit' ? 8 : 11});
  });
  edges.forEach(edge => {
    const from = placed.get(edge.source);
    const to = placed.get(edge.target);
    if (!from || !to) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('class', 'nexus-edge');
    line.setAttribute('x1', from.x);
    line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x);
    line.setAttribute('y2', to.y);
    svg.append(line);
  });
  nodes.forEach((item, index) => {
    const spot = placed.get(item.id);
    if (!spot) return;
    const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    group.setAttribute('class', 'nexus-node');
    if (reveal) {
      group.style.animation = 'bsc-rise .45s both';
      group.style.animationDelay = (index * 45) + 'ms';
    }
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('class', 'nexus-' + (item.kind || 'tool'));
    circle.setAttribute('cx', spot.x);
    circle.setAttribute('cy', spot.y);
    circle.setAttribute('r', spot.r);
    group.append(circle);
    if (item.id !== 'harness') {
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('class', 'nexus-label');
      label.setAttribute('x', spot.x);
      label.setAttribute('y', spot.y + spot.r + 16);
      label.setAttribute('text-anchor', 'middle');
      label.textContent = item.label;
      group.append(label);
    }
    svg.append(group);
  });
  board.append(svg);
}
function renderHarness(reveal) {
  const profile = state.harness || {accepted:false};
  const counter = $('#harness-counter');
  if (counter) counter.textContent = profile.accepted ? 'On' : '';
  const empty = $('#harness-empty');
  const stage = $('#harness-stage');
  const again = $('#harness-again');
  const remove = $('#harness-remove');
  if (!profile.accepted) {
    stage.hidden = true;
    again.hidden = true;
    remove.hidden = true;
    $('#harness-intro').textContent = 'Confirm the Hermes home for this workspace. The studio reads the map and does not start it.';
    $('#nexus-board').replaceChildren();
    $('#harness-directory').replaceChildren();
    empty.hidden = false;
    empty.replaceChildren();
    empty.append(node('p', '', 'Hermes is waiting for a location. The map is drawn only after you agree and accept.'));
    const button = node('button', 'primary', 'Find Hermes');
    button.type = 'button';
    button.addEventListener('click', () => openHarnessFind());
    empty.append(button);
    const waiting = $('#privacy-note');
    if (waiting) waiting.textContent = draftNote();
    return;
  }
  empty.hidden = true;
  stage.hidden = false;
  again.hidden = false;
  remove.hidden = false;
  const counts = profile.counts || {};
  $('#harness-intro').textContent = 'Accepted. This map is names and counts from the folder you confirmed.';
  $('#nexus-note').textContent = `${counts.skills || 0} skills · ${counts.memories || 0} memory files · ${counts.tools || 0} tools`;
  renderNexus(profile, reveal);
  renderDirectory(profile.directory);
  const note = $('#privacy-note');
  if (note) note.textContent = draftNote();
}
async function openHarnessFind() {
  if (harnessFindBusy) return;
  harnessFindBusy = true;
  state.harnessPrompted = true;
  state.harnessAgreed = '';
  state.harnessPick = '';
  $('#harness-path').value = '';
  $('#harness-dialog').showModal();
  startScan('Looking for Hermes.', 'The studio is checking the usual Hermes folders on this machine.');
  const started = performance.now();
  try {
    const found = await api('/api/harness/find', {});
    state.harnessHomes = found.homes || [];
    await dwell(started);
    stopScan();
    $('#harness-scan').hidden = true;
    $('#harness-results').hidden = false;
    $('#harness-dialog-title').textContent = state.harnessHomes.length ? 'Is this the harness?' : 'No Hermes home yet.';
    $('#harness-dialog-copy').textContent = state.harnessHomes.length ? 'Agree on the folder, then accept. The nexus is drawn after that.' : 'Paste the Hermes home, then agree and accept.';
    renderHarnessChoices();
  } catch (error) {
    stopScan();
    $('#harness-dialog').close();
    toast(error.message);
  } finally {
    harnessFindBusy = false;
  }
}
function maybeOfferHarness() {
  if (!state.provider.connected || state.harness?.accepted || state.harnessPrompted) return;
  if (document.querySelector('dialog[open]')) return;
  openHarnessFind();
}
async function agreeHarness() {
  const typed = $('#harness-path').value.trim();
  try {
    if (typed) {
      const previous = new Set((state.harnessHomes || []).map(home => home.path));
      startScan('Checking that folder.', 'Markers only. Secrets stay closed.');
      $('#harness-results').hidden = true;
      const started = performance.now();
      const found = await api('/api/harness/find', {path: typed});
      await dwell(started, 700);
      stopScan();
      state.harnessHomes = found.homes || [];
      const added = state.harnessHomes.find(home => !previous.has(home.path));
      const typedKey = pathKey(typed);
      const chosen = added || state.harnessHomes.find(home => pathKey(home.path) === typedKey || pathKey(home.path).endsWith('/' + typedKey));
      $('#harness-scan').hidden = true;
      $('#harness-results').hidden = false;
      if (!chosen) {
        renderHarnessChoices();
        toast('That folder does not look like Hermes. Choose the folder that contains its skills.');
        return;
      }
      state.harnessPick = chosen.path;
    }
    if (!state.harnessPick) {
      toast('Choose the folder first.');
      return;
    }
    state.harnessAgreed = state.harnessPick;
    $('#harness-dialog-title').textContent = 'Location agreed.';
    $('#harness-dialog-copy').textContent = 'Accept to build the nexus and the directory.';
    renderHarnessChoices();
    $('#harness-accept').disabled = false;
  } catch (error) {
    stopScan();
    $('#harness-scan').hidden = true;
    $('#harness-results').hidden = false;
    toast(error.message);
  }
}
async function removeHarness() {
  state.harness = await api('/api/harness/remove', {});
  state.harnessPrompted = true;
  state.harnessAgreed = '';
  state.harnessPick = '';
  await loadHarnessWorkspaces();
  await restoreHarnessProjects();
  renderHarness(false);
  toast('Harness disconnected; its saved workspace is retained. The Hermes folder was not changed.');
}
async function acceptHarness() {
  if (!state.harnessAgreed) return;
  $('#harness-agree').disabled = true;
  $('#harness-accept').disabled = true;
  startScan('Building the nexus.', 'Reading names and drawing the map.');
  const started = performance.now();
  try {
    state.harness = await api('/api/harness/accept', {path: state.harnessAgreed, agreed: true});
    await dwell(started, 700);
    stopScan();
    $('#harness-dialog').close();
    view('harness');
    await loadHarnessWorkspaces();
    await restoreHarnessProjects();
    renderHarness(true);
  } catch (error) {
    stopScan();
    $('#harness-scan').hidden = true;
    $('#harness-results').hidden = false;
    $('#harness-agree').disabled = false;
    $('#harness-accept').disabled = false;
    toast(error.message);
  }
}
function modelLabel(provider) {
  const hit=(state.localModels||[]).find(model=>model.id===provider.model&&sameBase(model.base_url, provider.base_url));
  if(hit) return hit.label;
  const leaf=String(provider.model||'').split(/[\\/]/).pop().replace(/\.gguf$/i,'');
  return leaf.length>32?leaf.slice(0,30)+'…':leaf;
}
function draftNote() {
  const p = state.provider || {};
  const base = p.connected ? (p.local ? 'Drafting with a local model on this machine.' : `Drafting via ${new URL(p.base_url).host}.`) : 'Offline template mode. No model requests.';
  return state.harness && state.harness.accepted ? base + ' The accepted harness is part of the draft.' : base;
}
function renderProvider() {
  const p=state.provider;
  const label=p.connected?modelLabel(p):(state.localModels.length===1?'1 local model':state.localModels.length?state.localModels.length+' local models':'Template');
  $('#mode-badge').textContent=p.connected?'◉ '+label:(state.localModels.length?'◉ '+label:'◉ Template mode');
  $('#sidebar-model').textContent=p.connected?label:'Template mode';
  $('#composer-mode').textContent=label;
  $('#privacy-note').textContent=draftNote();
  const status=$('#provider-status');
  if(status) status.textContent=p.connected?`Connected · ${label}`:'Template mode. No model requests yet.';
  if($('#provider-grid')) renderProviderCards();
}
function renderProviderCards() {
  const grid=$('#provider-grid'); if(!grid) return;
  grid.replaceChildren();
  PROVIDERS.forEach(preset=>{
    const connected=state.provider.connected&&((preset.base&&sameBase(state.provider.base_url, preset.base))||(preset.local&&state.provider.local));
    const card=node('button','provider-card'+(state.providerPick===preset.id?' selected':'')+(connected?' connected':''));
    card.type='button';
    const mark=node('span','provider-mark',preset.mark);
    mark.style.background=preset.color;
    const copy=node('span','provider-copy');
    copy.append(node('strong','',preset.name), node('small','',preset.maker));
    card.append(mark, copy);
    if(connected) card.append(node('span','provider-on','On'));
    card.addEventListener('click',()=>openProvider(preset));
    grid.append(card);
  });
}
function renderModelChips(preset) {
  const host=$('#model-chips'); host.replaceChildren();
  const models=preset.local?state.localModels.map(model=>model.id):preset.models;
  models.forEach(model=>{
    const hit=preset.local?state.localModels.find(item=>item.id===model):null;
    const chip=node('button','model-chip',hit?hit.label:model);
    chip.type='button';
    chip.title=model;
    chip.classList.toggle('active', $('#provider-model').value===model);
    chip.addEventListener('click',()=>{$('#provider-model').value=model; if(hit){$('#provider-url').value=hit.base_url;$('#provider-local').checked=true;$('#provider-key').value='';} renderModelChips(preset);});
    host.append(chip);
  });
}
function openProvider(preset) {
  state.providerPick=preset.id;
  const form=$('#provider-form');
  const keep=state.provider.connected&&((preset.base&&sameBase(state.provider.base_url, preset.base))||(preset.local&&state.provider.local));
  form.hidden=false;
  $('#sheet-mark').textContent=preset.mark;
  $('#sheet-mark').style.background=preset.color;
  $('#sheet-title').textContent=preset.name;
  $('#sheet-blurb').textContent=preset.blurb;
  $('#provider-url').value=keep?state.provider.base_url:preset.base;
  $('#provider-model').value=keep?state.provider.model:(preset.models[0]||'');
  $('#provider-key').value='';
  $('#provider-key').placeholder=preset.local?'No API key. Ollama fills the endpoint.':((state.savedKeys||[]).includes(preset.id)?'A key is saved. Leave this empty to use it, or paste a new one.':'Paste the key, then press Save key');
  const hint=$('#key-hint'); if(hint) hint.textContent=preset.local?'Not used for Ollama':'Saved outside the app';
  const saveKey=$('#save-key'); if(saveKey) saveKey.hidden=preset.local;
  showKeyConfirmation(preset);
  const fetchLocal=$('#fetch-local-sheet'); if(fetchLocal) fetchLocal.hidden=!preset.local;
  $('#provider-local').checked=keep?Boolean(state.provider.local):preset.local;
  $('#provider-json').checked=keep?state.provider.json_mode!==false:preset.json;
  $('#provider-token-field').value=keep?(state.provider.token_field||preset.token):preset.token;
  renderModelChips(preset);
  renderProviderCards();
  form.scrollIntoView({block:'nearest', behavior:'smooth'});
}
function workingCopy() {
  if (state.phaseLabel) return state.phaseLabel;
  return state.harness && state.harness.accepted ? 'Analyzing harness' : 'Working on your skill…';
}
function paintPhase(label) {
  state.phaseLabel = label || workingCopy();
  const line = document.querySelector('.message.working .working-line');
  if (line) {
    const wave = line.querySelector('.work-wave');
    line.replaceChildren();
    if (wave) line.append(wave);
    line.append(document.createTextNode(state.phaseLabel));
  }
  if (state.pending && $('#status-text')) $('#status-text').textContent = state.phaseLabel;
}
function watchPhase() {
  window.clearInterval(phaseWatch);
  if (!state.harness || !state.harness.accepted || !state.project) return;
  phaseWatch = window.setInterval(async () => {
    if (!state.pending) { window.clearInterval(phaseWatch); return; }
    try {
      const phase = await api('/api/draft-phase?id=' + encodeURIComponent(state.project.id));
      if (phase.label && phase.label !== state.phaseLabel) paintPhase(phase.label);
    } catch (error) {}
  }, 700);
}
function stopPhaseWatch() {
  window.clearInterval(phaseWatch);
  phaseWatch = 0;
  state.phaseLabel = '';
}
function skillLink(project) {
  const install=project?.install||{};
  const anchor=node('a','skill-link', install.folder||'Open the skill');
  anchor.href=install.url;
  anchor.addEventListener('click',event=>{
    event.preventDefault();
    run(async()=>{
      await api('/api/open-skill',{id:project.id});
      toast('Opened the skill folder.');
    });
  });
  return anchor;
}
function fillMessage(parent, content, project) {
  const url=project?.install?.url||'';
  if(!url || !String(content).includes(url)) {
    parent.append(document.createTextNode(content));
    return;
  }
  String(content).split(url).forEach((part,index,parts)=>{
    if(part) parent.append(document.createTextNode(part));
    if(index<parts.length-1) parent.append(skillLink(project));
  });
}
function messageCard(role, content, project) {
  const card=node('article',`message ${role}`);
  card.append(node('div','message-avatar',role==='user'?'YOU':'✳'));
  const body=node('div','message-content');
  const paragraph=node('p');
  fillMessage(paragraph, content, role==='assistant'?project:null);
  body.append(node('div','message-header',role==='user'?'You':'Bot Skill Creator'), paragraph);
  card.append(body);
  return card;
}
function renderMessages() {
  const p=state.project, target=$('#messages');target.replaceChildren();
  const saved=p?.messages||[];
  saved.forEach((msg,index)=>{
    const card=messageCard(msg.role, msg.content, p);
    if(msg.role!=='user') card.querySelector('.message-header').append(node('span','',p.draft_source==='offline_template'?'TEMPLATE':'MODEL DRAFT'));
    if(state.revealReply&&msg.role==='assistant'&&index===saved.length-1) card.classList.add('just-sent');
    if(msg.role==='assistant'&&index===saved.length-1&&p.plan) {
      const badge=node('div','message-card');badge.append(node('span','','▧'),node('strong','',p.plan.name),node('span','',p.clarification?.pending?'One question first':'Draft ready ↗'));
      card.querySelector('.message-content').append(badge);
    }
    if(msg.role==='assistant'&&index===saved.length-1&&p.clarification?.pending) {
      const again=node('button','quiet','Answer this');
      again.type='button';
      again.addEventListener('click',()=>{state.clarifyDismissed=false; openClarify(p);});
      card.querySelector('.message-content').append(again);
    }
    target.append(card);
  });
  if(state.pending) {
    const yours=messageCard('user', state.pending, p);
    yours.classList.add('just-sent');
    const working=node('article','message assistant working just-sent');
    working.setAttribute('role','status');
    const avatar=node('div','message-avatar','✳');
    const orbit=node('span','work-orbit');
    orbit.setAttribute('aria-hidden','true');
    orbit.append(node('i'));
    avatar.prepend(orbit);
    const body=node('div','message-content');
    const line=node('p','working-line',workingCopy());
    const wave=node('span','work-wave');
    wave.setAttribute('aria-hidden','true');
    wave.append(node('i'), node('i'), node('i'), node('i'), node('i'));
    const track=node('span','work-track');
    track.setAttribute('aria-hidden','true');
    track.append(node('i'));
    line.prepend(wave);
    body.append(node('div','message-header','Bot Skill Creator'), line, track);
    working.append(avatar, body);
    target.append(yours, working);
  }
  target.setAttribute('aria-busy', state.pending?'true':'false');
  const talking=Boolean(saved.length||state.pending);
  $('#starters').hidden=talking;
  $('#hero').hidden=talking;
  const scroller=$('#conversation-scroll');
  if(talking) {
    const follow=()=>{scroller.scrollTo({top:scroller.scrollHeight, behavior:state.pending?'smooth':'auto'});};
    if(state.pending) requestAnimationFrame(follow);
    else follow();
  }
}
function renderProject(project) {
  state.project=project;
  $('#bound-target').textContent=project.target ? 'Draft target: '+project.target+' · Static inspection; execution unverified' : 'Draft target: unbound';
  $('#validate-draft').disabled=!project.plan;
  $('#install-draft').disabled=!project.harness_id||!project.sandbox?.ok||!!project.install?.installed;
  if(state.file==='tools/run_tool.py') state.file='SKILL.md';
  $('#project-title').textContent=project.plan?.name||'Untitled skill';
  $('#skill-name').textContent=project.plan?.name||'Your next capability';
  $('#skill-desc').textContent=project.plan?.description||'A clear contract. A portable folder.';
  $('#draft-status').textContent=project.install?.installed?'INSTALLED':project.clarification?.pending?'ONE QUESTION':project.plan?'READY':'DRAFT';
  renderChecks(project.plan);
  $('#api-counter').textContent=project.api?'1':'0';
  const attached=$('#attached-bar');attached.hidden=!project.api;
  attached.textContent=project.api?`⌘ ${project.api.name} · ${project.selected_ids.length} selected operations · Contract only`:'';
  $('#validation-note').textContent=proofLine(project);
  renderFile();renderMessages();renderAPI();renderStatus();
}
function proofLine(project) {
  if (project?.clarification?.pending) return 'One question first · Then I keep going';
  if (!project?.validation) return 'No draft yet · Nothing has been executed';
  const mark = project.validation.ok ? '✓' : '!';
  const files = `${project.validation.file_count} files`;
  if (project.sandbox?.ok && project.install?.installed) return `${mark} ${files} · Sandbox passed · Installed at ${project.install.folder}`;
  if (project.sandbox && project.sandbox.ok === false) return `${mark} ${files} · Sandbox failed · Not installed`;
  if (project.sandbox?.ok) return `${mark} ${files} · Sandbox passed · Not installed in a harness`;
  return `${mark} ${files} · Static checks ${project.validation.ok ? 'passed' : 'failed'} · Not live-tested`;
}
function renderFile() {
  const content=state.project?.files?.[state.file];
  $('#code-preview').textContent=content||'# Your skill starts here\n\nDescribe a goal in the chat.\nImport an API, or stay offline.\n\nWe’ll build the structure.\nYou keep the final say.';
  $$('.file-tabs [data-file]').forEach(x=>{x.classList.toggle('active',x.dataset.file===state.file);x.setAttribute('aria-selected',x.dataset.file===state.file?'true':'false');});
}
async function refreshLibrary() {
  const bootstrap=await api('/api/bootstrap?harness_id='+encodeURIComponent(state.harness?.id||''));state.projects=bootstrap.projects;
  $('#library-counter').textContent=state.projects.filter(p=>p.revision>0).length;
  const recent=$('#recent-projects');recent.replaceChildren();
  state.projects.filter(p=>p.revision>0).slice(0,6).forEach(p=>{
    const button=node('button','',p.name);button.title=p.name;
    button.addEventListener('click',()=>run(()=>openProject(p.id)));recent.append(button);
  });renderLibrary();
}
async function openProject(id) {renderProject(await api('/api/project?id='+encodeURIComponent(id)));view('studio');}
async function createProject() {renderProject(await api('/api/projects',{harness_id:state.harness?.id||null}));view('studio');await refreshLibrary();$('#message-input').focus();}
function renderLibrary() {
  const grid=$('#library-grid');grid.replaceChildren();
  const projects=state.projects.filter(p=>p.revision>0);
  if(!projects.length) {grid.append(node('div','explain-card','Your first skill starts in the studio. It shows up here after the first draft.'));return;}
  projects.forEach(p=>{
    const card=node('article','library-card');
    card.append(node('div','skill-glyph','✳'),node('h3','',p.name));
    const detail=node('p','',p.description||'Draft on this machine');
    card.append(detail,node('small','',`Revision ${p.revision} · ${new Date(p.updated_at*1000).toLocaleDateString()}`));
    const actions=node('div','skill-actions');
    const open=node('button','', 'Open');
    const pack=node('button','', 'Package');
    const exp=node('button','', 'Export');
    const del=node('button','danger', 'Delete');
    open.addEventListener('click',()=>run(()=>openProject(p.id)));
    pack.addEventListener('click',()=>run(()=>showPackage(p.id)));
    exp.addEventListener('click',()=>run(()=>exportSkill(p.id)));
    const confirm=node('div','delete-confirm');
    confirm.hidden=true;
    confirm.append(node('span','','Delete this skill from this machine?'));
    const keep=node('button','','Keep');
    const yes=node('button','danger','Delete');
    keep.addEventListener('click',()=>{confirm.hidden=true;});
    yes.addEventListener('click',()=>run(()=>removeSkill(p.id)));
    confirm.append(keep,yes);
    del.addEventListener('click',()=>{confirm.hidden=false;});
    actions.append(open,pack,exp,del);
    card.append(actions,confirm);
    grid.append(card);
  });
}
async function loadSkill(id) {
  return api('/api/project?id='+encodeURIComponent(id));
}
function showPackageFile(name) {
  const project=state.packageProject;
  state.packageFile=name;
  $('#package-body').textContent=project.files[name]||'';
  $$('#package-files button').forEach(button=>button.classList.toggle('active',button.dataset.file===name));
}
async function showPackage(id) {
  const project=await loadSkill(id);
  state.packageProject=project;
  $('#package-title').textContent=project.plan?.name||'Untitled skill';
  const count=Object.keys(project.files||{}).length;
  $('#package-meta').textContent=count?`${count} files · Revision ${project.revision} · Static package, not a live run`:'This draft has no package yet. Open it in the studio and describe the skill.';
  const files=$('#package-files');files.replaceChildren();
  const names=Object.keys(project.files||{});
  names.forEach(name=>{
    const button=node('button','',name);
    button.type='button';
    button.dataset.file=name;
    button.addEventListener('click',()=>showPackageFile(name));
    files.append(button);
  });
  $('#package-body').textContent=names.length?project.files[names[0]]:'Describe the skill in the studio, then come back to read the package.';
  if(names.length) showPackageFile(names[0]);
  $('#package-dialog').showModal();
}
async function downloadZip(project) {
  if(!project.plan||!project.validation?.ok) throw new Error('This draft is not ready to export. Open it and finish the blueprint.');
  const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json','X-BSC-Token':state.token},body:JSON.stringify({id:project.id,fingerprint:project.export_fingerprint})});
  if(!response.ok){const e=await response.json();throw new Error(e.error||'Export stopped.');}
  const url=URL.createObjectURL(await response.blob());
  const link=node('a');link.href=url;link.download=(project.plan.name||'skill')+'.zip';
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),3000);
}
async function exportSkill(id) {
  const project=state.packageProject?.id===id?state.packageProject:await loadSkill(id);
  await downloadZip(project);
  toast('Skill package exported.');
}
async function removeSkill(id) {
  await api('/api/projects/delete',{id});
  if(state.packageProject?.id===id){state.packageProject=null;$('#package-dialog').close();}
  if(state.project?.id===id){
    const rest=state.projects.filter(item=>item.id!==id&&item.revision>0);
    if(rest.length) renderProject(await loadSkill(rest[0].id));
    else renderProject(await api('/api/projects',{harness_id:state.harness?.id||null}));
  }
  await refreshLibrary();
  view('library');
  toast('Skill deleted from this machine.');
}
function openAPI() {$('#api-dialog').showModal();$('#api-json').focus();}
function renderAPI() {
  const target=$('#api-content');target.replaceChildren();const p=state.project;
  if(!p?.api) {
    const empty=node('div','api-card');empty.append(node('div','skill-glyph','⌘'),node('h2','','Start with a contract.'),node('p','','Choose a bundled OpenAPI JSON file or try the fictional Warehouse API. Select only the operations your workflow needs.'));
    const b=node('button','quiet','Import an API →');b.addEventListener('click',openAPI);empty.append(b);target.append(empty);return;
  }
  const card=node('section','api-card');card.append(node('span','tiny-pill','IMPORTED · NOT EXECUTED'),node('h2','',p.api.name),node('div','api-url',p.api.base_url||'Host adapter must supply a server URL'));
  p.api.operations.forEach(op=>{
    const label=node('label','operation');const input=node('input');input.type='checkbox';input.value=op.id;input.checked=p.selected_ids.includes(op.id);input.className='operation-checkbox';
    const info=node('span','op-info');info.append(node('strong','',op.id),node('small','',op.summary));
    label.append(input,node('span',`method ${op.effect==='write_candidate'?'write':''}`,op.method),info,node('span','op-effect','Host approval required'));card.append(label);
  });
  const bottom=node('div','api-bottom');bottom.append(node('span','dialog-note',`${p.selected_ids.length} / ${p.api.operations.length} operations selected`));
  const save=node('button','primary','Save capabilities →');
  save.addEventListener('click',()=>run(async()=>{
    const selected=$$('.operation-checkbox:checked').map(x=>x.value);
    renderProject(await api('/api/select',{id:state.project.id,selected_ids:selected}));await refreshLibrary();toast('Selected capabilities saved. Refine the blueprint to use them.');
  }));bottom.append(save);card.append(bottom);
  if(p.api.warnings.length) card.append(node('p','',p.api.warnings.join('\n')));
  target.append(card);
}
function providerDialog() {
  view('apis');
  const current=state.provider;
  const match=PROVIDERS.find(preset=>current.connected&&preset.base&&sameBase(current.base_url, preset.base));
  openProvider(match||PROVIDERS.find(preset=>preset.id===state.providerPick)||PROVIDERS[0]);
}
async function calculate() {
  try {
    const result=await api('/api/score',{success:Number($('#math-s').value),failure:Number($('#math-f').value),unknown:Number($('#math-u').value)});
    $('#math-result').textContent=`q = ${result.q.toFixed(4)}   μ = ${result.mu.toFixed(4)}\nθ = ${result.theta.toFixed(4)}   score = ${result.score.toFixed(4)}\nIllustrative cost 0.20 · λ 0.15 · Not calibrated`;
  } catch(error) {toast(error.message);}
}
function submitChat(message) {
  if(state.busy || !message || !state.project) return;
  state.pending=message;
  state.phaseLabel=state.harness&&state.harness.accepted?'Analyzing harness':'Working on your skill…';
  renderMessages();
  watchPhase();
  $('#message-input').focus();
  run(async()=>{
    try {
      const project=await api('/api/chat',{id:state.project.id,message});
      stopPhaseWatch();
      state.pending='';
      state.clarifyDismissed=false;
      state.revealReply=true;
      renderProject(project);
      state.revealReply=false;
      await refreshLibrary();
    } catch(error) {
      stopPhaseWatch();
      state.pending='';
      const field=$('#message-input');
      if(!field.value.trim()) {field.value=message; fitComposer();}
      renderMessages();
      throw error;
    }
  });
}
function openClarify(project) {
  const ask=project?.clarification;
  const dialog=$('#clarify-dialog');
  if(!ask?.pending || !ask.questions?.length || !dialog) return;
  const fields=$('#clarify-fields');
  fields.replaceChildren();
  ask.questions.forEach((item,index)=>{
    const block=node('div','clarify-question');
    block.append(node('p','clarify-ask',item.question));
    (item.choices||[]).forEach((choice,choiceIndex)=>{
      const label=node('label','clarify-choice');
      const input=node('input');
      input.type='radio';
      input.name='clarify-'+index;
      input.value=choice;
      if(choiceIndex===0) input.checked=true;
      const copy=node('span','clarify-choice-copy',choice);
      label.append(input, copy);
      if(choiceIndex===0) label.append(node('span','clarify-rec','Recommended'));
      block.append(label);
    });
    const free=node('input');
    free.type='text';
    free.className='clarify-free';
    free.placeholder=item.choices?.length?'Or tell me in your own words':'Type your answer';
    free.maxLength=500;
    free.setAttribute('aria-label', item.question);
    block.append(free);
    fields.append(block);
  });
  if(!dialog.open) dialog.showModal();
  const focus=fields.querySelector('input');
  if(focus) focus.focus();
}
function maybeAsk(project) {
  if(!project?.clarification?.pending || state.clarifyDismissed || state.busy) return;
  openClarify(project);
}
function clarifyMessage() {
  const lines=[];
  for(const block of $$('#clarify-fields .clarify-question')) {
    const question=block.querySelector('.clarify-ask').textContent;
    const typed=block.querySelector('.clarify-free').value.trim();
    const picked=block.querySelector('input[type=radio]:checked');
    const answer=typed || (picked?picked.value:'');
    if(!answer) return '';
    lines.push(question+' — '+answer);
  }
  return lines.length ? ['Here you go:'].concat(lines).join(String.fromCharCode(10)) : '';
}
$('#chat-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(state.busy) return;
  const message=$('#message-input').value.trim();
  if(!message) return;
  $('#message-input').value='';
  fitComposer();
  submitChat(message);
});
$('#clarify-form').addEventListener('submit',event=>{
  event.preventDefault();
  const message=clarifyMessage();
  if(!message) { toast('I need an answer before I can keep going.'); return; }
  state.clarifyDismissed=true;
  $('#clarify-dialog').close();
  submitChat(message);
});
$('#clarify-close').addEventListener('click',()=>{state.clarifyDismissed=true;});
$('#message-input').addEventListener('input',fitComposer);
$('#message-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#chat-form').requestSubmit();}});
$$('.starter').forEach(button=>button.addEventListener('click',()=>{$('#message-input').value=button.dataset.prompt;fitComposer();$('#message-input').focus();}));
$$('[data-view]').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
$('#new-project').addEventListener('click',()=>run(createProject));
$('#harness-dismiss').addEventListener('click',()=>{stopScan();state.harnessPrompted=true;$('#harness-dialog').close();});
$('#harness-close').addEventListener('click',()=>{stopScan();state.harnessPrompted=true;});
$('#harness-again').addEventListener('click',()=>openHarnessFind());
$('#harness-remove').addEventListener('click',()=>run(removeHarness));
$('#harness-path').addEventListener('input',()=>{$('#harness-agree').disabled=!$('#harness-path').value.trim()&&!state.harnessPick;});
$('#harness-agree').addEventListener('click',()=>agreeHarness());
$('#harness-accept').addEventListener('click',()=>acceptHarness());
$('#composer-api').addEventListener('click',openAPI);$('#import-api-button').addEventListener('click',openAPI);
$('#api-upload').addEventListener('change',async(event)=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>1000000){toast('Choose a JSON document smaller than 1 MB.');return;}
  $('#api-json').value=await file.text();
});
$('#load-example').addEventListener('click',()=>run(async()=>{$('#api-json').value=JSON.stringify(await api('/api/example'),null,2);}));
$('#import-document').addEventListener('click',()=>run(async()=>{
  renderProject(await api('/api/import',{id:state.project.id,document:$('#api-json').value}));
  $('#api-json').value='';$('#api-dialog').close();await refreshLibrary();view('apis');toast('Contract imported. Choose the operations to include.');
}));
function renderLocalModels() {
  const list=$('#local-model-list'); if(!list) return;
  list.replaceChildren();
  if(!state.localModels.length) {
    list.append(node('p','picker-empty','Looking for Ollama. Start it, then Fetch.'));
    return;
  }
  state.localModels.forEach(model=>{
    const button=node('button','local-model');
    button.type='button';
    const using=state.provider.connected&&state.provider.local&&state.provider.model===model.id&&sameBase(state.provider.base_url, model.base_url);
    button.classList.toggle('selected', using);
    const copy=node('span','local-copy');
    copy.append(node('strong','',model.label), node('small','',model.detail));
    button.append(copy, node('span','local-use', using?'Using':'Use'));
    button.addEventListener('click',()=>run(()=>useLocalModel(model)));
    list.append(button);
  });
}
let localScanBusy=false;
let localWatch=null;
async function scanLocalModels() {
  if(localScanBusy) return state.localModels;
  localScanBusy=true;
  try {
    const data=await api('/api/local-models');
    state.localModels=data.models||[];
    renderLocalModels();
    renderProvider();
    if(state.providerPick==='local'&&$('#provider-form')&&!$('#provider-form').hidden) renderModelChips(PROVIDERS.find(preset=>preset.id==='local'));
    return state.localModels;
  } finally { localScanBusy=false; }
}
function fillLocalForm(model) {
  const form=$('#provider-form');
  if(!form||form.hidden||state.providerPick!=='local') return;
  $('#provider-url').value=model.base_url;
  $('#provider-model').value=model.id;
  $('#provider-key').value='';
  $('#provider-local').checked=true;
  $('#provider-json').checked=model.json_mode===true;
  $('#provider-token-field').value=model.token_field||'max_tokens';
  renderModelChips(PROVIDERS.find(preset=>preset.id==='local'));
}
function preferredLocal(models) {
  const saved=state.localSaved;
  if(saved&&saved.model) {
    const hit=models.find(model=>model.id===saved.model&&sameBase(model.base_url, saved.base_url));
    if(hit) return hit;
  }
  return models.length===1?models[0]:null;
}
function showKeyConfirmation(preset) {
  const note=$('#key-confirmation');
  if(!note) return;
  if(!preset) preset=PROVIDERS.find(item=>item.id===state.providerPick);
  if(!preset) { note.hidden=true; return; }
  if(preset.local) {
    note.hidden=!state.localSaved;
    note.textContent=state.localSaved?'Saved for the next session. No API key is used.':'';
    return;
  }
  const saved=(state.savedKeys||[]).includes(preset.id);
  note.hidden=!saved;
  note.textContent=saved?'Saved for the next session.':'';
}
async function useLocalModel(model) {
  state.holdLocal=false;
  state.providerPick='local';
  state.provider=await api('/api/provider',{provider_id:'local',base_url:model.base_url,model:model.id,api_key:'',local:true,json_mode:model.json_mode===true,token_field:model.token_field||'max_tokens'});
  if(state.provider.local_saved) state.localSaved={base_url:model.base_url,model:model.id,token_field:model.token_field||'max_tokens',json_mode:model.json_mode===true};
  $('#model-picker').hidden=true;
  $('#composer-model').setAttribute('aria-expanded','false');
  fillLocalForm(model);
  renderProvider();
  showKeyConfirmation(PROVIDERS.find(item=>item.id==='local'));
  toast(state.provider.confirmation||(model.label+' linked. Saved for the next session. No API key is used.'));
  maybeOfferHarness();
}
async function fetchLocalModel() {
  state.holdLocal=false;
  const models=await scanLocalModels();
  const pick=preferredLocal(models);
  if(pick) { await useLocalModel(pick); return; }
  if(!models.length) { toast('Still looking for Ollama.'); return; }
  const picker=$('#model-picker'); picker.hidden=false; $('#composer-model').setAttribute('aria-expanded','true');
  toast(models.length+' Ollama models are available. Choose one.');
}
function watchLocalModels() {
  if(localWatch) return;
  const look=()=>{
    if(document.hidden||state.holdLocal||state.provider.connected||localScanBusy) return;
    scanLocalModels().then(models=>{
      if(state.holdLocal||state.provider.connected) return;
      const pick=preferredLocal(models);
      if(!pick) return;
      return useLocalModel(pick);
    }).catch(()=>{});
  };
  look();
  localWatch=setInterval(look, 4000);
}
function toggleModelPicker() {
  const picker=$('#model-picker');
  const opening=picker.hidden;
  picker.hidden=!opening;
  $('#composer-model').setAttribute('aria-expanded', opening?'true':'false');
  if(opening) scanLocalModels().catch(error=>toast(error.message));
}
$('#open-provider').addEventListener('click',providerDialog);
$('#composer-model').addEventListener('click',event=>{event.stopPropagation();toggleModelPicker();});
$('#rescan-models').addEventListener('click',()=>scanLocalModels().catch(error=>toast(error.message)));
$('#picker-offline').addEventListener('click',()=>run(async()=>{state.holdLocal=true;state.provider=await api('/api/provider/disconnect',{});$('#model-picker').hidden=true;renderProvider();toast('Offline template mode restored.');}));
$('#fetch-local').addEventListener('click',()=>run(fetchLocalModel));
$('#fetch-local-sheet').addEventListener('click',()=>run(fetchLocalModel));
$('#picker-providers').addEventListener('click',()=>{$('#model-picker').hidden=true;providerDialog();});
document.addEventListener('click',event=>{
  const picker=$('#model-picker');
  if(!picker||picker.hidden) return;
  if(event.target.closest('#model-picker')||event.target.closest('#composer-model')) return;
  picker.hidden=true;
  $('#composer-model').setAttribute('aria-expanded','false');
});
$('#provider-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
  const preset=PROVIDERS.find(item=>item.id===state.providerPick);
  state.provider=await api('/api/provider',{provider_id:state.providerPick,base_url:$('#provider-url').value,model:$('#provider-model').value,api_key:$('#provider-key').value,
    local:$('#provider-local').checked,json_mode:$('#provider-json').checked,token_field:$('#provider-token-field').value});
  $('#provider-key').value='';
  if(state.provider.local_saved) state.localSaved={base_url:state.provider.base_url,model:state.provider.model,token_field:state.provider.token_field,json_mode:state.provider.json_mode===true};
  renderProvider();
  if(preset) showKeyConfirmation(preset);
  toast(state.provider.confirmation||'Provider ready. Your next chat message will use it.');
  maybeOfferHarness();
});});
$('#save-key').addEventListener('click',()=>run(async()=>{
  const preset=PROVIDERS.find(item=>item.id===state.providerPick);
  if(!preset||preset.local) return;
  const result=await api('/api/provider/key',{provider:preset.id,api_key:$('#provider-key').value});
  $('#provider-key').value='';
  if(!(state.savedKeys||[]).includes(preset.id)) state.savedKeys.push(preset.id);
  $('#provider-key').placeholder='A key is saved. Leave this empty to use it, or paste a new one.';
  showKeyConfirmation(preset);
  toast(result.confirmation||'Saved for the next session.');
}));
$('#disconnect-model').addEventListener('click',()=>run(async()=>{state.holdLocal=true;state.provider=await api('/api/provider/disconnect',{});$('#provider-key').value='';renderProvider();toast('Offline template mode restored.');}));
$$('.file-tabs [data-file]').forEach(button=>button.addEventListener('click',()=>{state.file=button.dataset.file;renderFile();}));
$('#copy-file').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#code-preview').textContent);toast('Current file copied.');}catch{toast('Clipboard unavailable. Select and copy the preview text.');}});
$('#edit-plan').addEventListener('click',()=>{$('#plan-json').value=JSON.stringify(state.project.plan,null,2);$('#plan-dialog').showModal();});
$('#save-plan').addEventListener('click',()=>run(async()=>{
  let plan;try{plan=JSON.parse($('#plan-json').value);}catch{throw new Error('Blueprint must be valid JSON.');}
  renderProject(await api('/api/plan',{id:state.project.id,plan}));$('#plan-dialog').close();await refreshLibrary();toast('Blueprint updated. Export approval will bind to this revision.');
}));
$('#export').addEventListener('click',()=>{
  state.reviewed={id:state.project.id,fingerprint:state.project.export_fingerprint,name:state.project.plan.name};
  const summary=$('#export-summary');summary.replaceChildren();
  summary.append(node('strong','',state.project.plan.name),node('div','',`${state.project.validation.file_count} files · ${state.project.selected_ids.length} API operations · Revision ${state.project.revision}`),node('small','',`Review fingerprint: ${state.reviewed.fingerprint.slice(0,24)}…`));
  const inspect=node('button','quiet','Inspect every exported file ↗');
  inspect.addEventListener('click',()=>{$('#reference-text').textContent=Object.entries(state.project.files).map(([name,body])=>'━━ '+name+' ━━\n\n'+body).join('\n\n');$('#text-dialog').showModal();});
  summary.append(node('br'),inspect);
  $('#export-dialog').showModal();
});
$('#package-open').addEventListener('click',()=>{if(!state.packageProject)return;const id=state.packageProject.id;$('#package-dialog').close();run(()=>openProject(id));});
$('#package-export').addEventListener('click',()=>run(async()=>{if(!state.packageProject)return;await downloadZip(state.packageProject);toast('Skill package exported.');}));
$('#confirm-export').addEventListener('click',()=>run(async()=>{
  const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json','X-BSC-Token':state.token},body:JSON.stringify(state.reviewed)});
  if(!response.ok){const e=await response.json();throw new Error(e.error||'Export stopped.');}
  const url=URL.createObjectURL(await response.blob());const link=node('a');link.href=url;link.download=state.reviewed.name+'.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
  $('#export-dialog').close();toast('Reviewed skill exported. File integrity verified.');
}));
$('#calculate').addEventListener('click',calculate);
$('#read-math').addEventListener('click',()=>run(async()=>{$('#reference-text').textContent=(await api('/api/math')).markdown;$('#text-dialog').showModal();}));
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='n'){event.preventDefault();if(!document.querySelector('dialog[open]'))run(createProject);}});
if(/Mac|iPhone|iPad/.test(navigator.platform||'')||/Mac OS/.test(navigator.userAgent)){const shortcut=$('#new-shortcut');if(shortcut)shortcut.textContent='⌘N';}
const queryTheme=new URLSearchParams(location.search).get('theme');
applyTheme(queryTheme==='dark'||queryTheme==='light'?queryTheme:(document.documentElement.dataset.theme||savedTheme()));
$('#theme-toggle').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem('bsc-theme',next);}catch(error){}applyTheme(next);});
function studioClient() {
  const key = 'bsc-page';
  try {
    let id = sessionStorage.getItem(key) || '';
    if (!/^[A-Za-z0-9_-]{8,80}$/.test(id)) {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
      sessionStorage.setItem(key, id);
    }
    return id;
  } catch (error) {
    return 'pagefallback01';
  }
}
function holdStudioOpen() {
  if (!state.untilClose || !state.token || state.holdingStudio) return;
  state.holdingStudio = true;
  state.clientId = studioClient();
  const beat = () => {
    fetch('/api/presence', {method:'POST', keepalive:true, headers:{'Content-Type':'application/json','X-BSC-Token':state.token}, body:JSON.stringify({client:state.clientId})}).catch(()=>{});
  };
  beat();
  setInterval(beat, 2000);
  window.addEventListener('pagehide', beat);
}
(async()=>{
  try{const data=await api('/api/bootstrap');state.token=data.token;state.untilClose=data.until_close===true;state.projects=data.projects;state.provider=data.provider;state.savedKeys=data.saved_keys||[];state.localSaved=data.local_saved||null;renderProvider();
    holdStudioOpen();
    state.harness=await api('/api/harness');
    if(state.projects.length) await openProject(state.projects[0].id);else renderProject(await api('/api/projects',{harness_id:state.harness?.id||null}));await refreshLibrary();
    watchLocalModels();
    const startView=new URLSearchParams(location.search).get('view');
    state.harness=await api('/api/harness');
    await loadHarnessWorkspaces();
    renderHarness(false);
    if(startView==='apis'||startView==='library'||startView==='algorithm'||startView==='harness') view(startView);
    maybeOfferHarness();
  }catch(error){toast(error.message);$('#status-text').textContent='Studio could not load. Open the printed local URL.';}
})();

async function loadHarnessWorkspaces() {
  const data=await api('/api/harnesses'); state.harnessWorkspaces=data.harnesses;
  const select=$('#harness-workspace'); select.replaceChildren();
  const empty=node('option','','Unbound drafts'); empty.value=''; select.append(empty);
  for(const h of data.harnesses) {const option=node('option','',h.name+' · '+h.id.slice(0,6));option.value=h.id;select.append(option);}
  select.value=state.harness?.id||'';
  $('#edit-harness-context').disabled=!state.harness?.id;
}
async function restoreHarnessProjects() {
  await refreshLibrary();
  if(state.projects.length) await openProject(state.projects[0].id);
  else await createProject();
}
$('#harness-workspace').addEventListener('change',()=>run(async()=>{
  state.harness=await api('/api/harness/switch',{id:$('#harness-workspace').value||null});
  await loadHarnessWorkspaces(); await restoreHarnessProjects(); renderHarness(false);
}));
$('#connect-harness').addEventListener('click',()=>openHarnessFind());
$('#edit-harness-context').addEventListener('click',()=>{
  const h=state.harnessWorkspaces.find(h=>h.id===$('#harness-workspace').value);
  if(!h)return; state.contextTarget=h.id; $('#harness-context').value=h.context; $('#harness-context-dialog').showModal();
});
$('#save-harness-context').addEventListener('click',()=>run(async()=>{
  await api('/api/harness/context',{id:state.contextTarget,context:$('#harness-context').value});
  await loadHarnessWorkspaces(); $('#harness-context-dialog').close(); toast('Harness context saved.');
}));
$('#validate-draft').addEventListener('click',()=>run(async()=>{
  renderProject(await api('/api/validate',{id:state.project.id})); await refreshLibrary();
}));
$('#install-draft').addEventListener('click',()=>{
  const p=state.project;
  state.installReview={id:p.id,fingerprint:p.install_fingerprint,approved:true};
  $('#install-summary').textContent=p.plan.name+' · Revision '+p.revision+' · Target: '+p.target+' · Snapshot '+p.snapshot_id;
  $('#install-dialog').showModal();
});
$('#confirm-install').addEventListener('click',()=>run(async()=>{
  const result=await api('/api/install',state.installReview);
  if(state.project?.id===result.id)renderProject(result);
  $('#install-dialog').close(); toast(result.install.installed?'Reviewed skill installed.':result.install.reason);
}));
