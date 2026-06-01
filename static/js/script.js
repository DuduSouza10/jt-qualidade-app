const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const els = {
  sidebarLinks: $$(".sidebar-link"),
  panelWaybill: $("#panelWaybill"),
  panelPod: $("#panelPod"),
  heroTitle: $("#heroTitle"),
  heroDescription: $("#heroDescription"),

  username: $("#username"),
  password: $("#password"),
  chromeProfile: $("#chromeProfile"),
  savePassword: $("#savePassword"),
  recreateProfile: $("#recreateProfile"),
  waybills: $("#waybills"),

  podUsername: $("#podUsername"),
  podPassword: $("#podPassword"),
  podChromeProfile: $("#podChromeProfile"),
  podSavePassword: $("#podSavePassword"),
  podRecreateProfile: $("#podRecreateProfile"),
  podIds: $("#podIds"),

  startBtn: $("#startBtn"),
  stopBtn: $("#stopBtn"),
  exportBtn: $("#exportBtn"),
  checkUpdateBtn: $("#checkUpdateBtn"),
  applyUpdateBtn: $("#applyUpdateBtn"),
  updateStatus: $("#updateStatus"),
  togglePassword: $("#togglePassword"),
  clearLogsBtn: $("#clearLogsBtn"),

  podStartBtn: $("#podStartBtn"),
  podStopBtn: $("#podStopBtn"),
  podExportBtn: $("#podExportBtn"),
  togglePodPassword: $("#togglePodPassword"),
  podClearLogsBtn: $("#podClearLogsBtn"),

  statusText: $("#statusText"),
  statusSubText: $("#statusSubText"),

  progressLabel: $("#progressLabel"),
  progressPercent: $("#progressPercent"),
  progressFill: $("#progressFill"),

  podProgressLabel: $("#podProgressLabel"),
  podProgressPercent: $("#podProgressPercent"),
  podProgressFill: $("#podProgressFill"),

  logsBox: $("#logsBox"),
  podLogsBox: $("#podLogsBox"),
  resultsBody: $("#resultsBody"),
  resultsCount: $("#resultsCount"),
  podResultsBody: $("#podResultsBody"),
  podResultsCount: $("#podResultsCount"),

  exportModal: $("#exportModal"),
  exportModalTitle: $("#exportModalTitle"),
  exportPreviewHead: $("#exportPreviewHead"),
  closeExportModal: $("#closeExportModal"),
  cancelExportBtn: $("#cancelExportBtn"),
  confirmExportBtn: $("#confirmExportBtn"),
  exportFileName: $("#exportFileName"),
  exportFolder: $("#exportFolder"),
  exportTotal: $("#exportTotal"),
  exportPreviewBody: $("#exportPreviewBody"),

  viewResultsBtn: $("#viewResultsBtn"),
  viewPodResultsBtn: $("#viewPodResultsBtn"),
  resultsSummaryBox: $("#resultsSummaryBox"),
  podResultsSummaryBox: $("#podResultsSummaryBox"),

  resultsModal: $("#resultsModal"),
  resultsModalTitle: $("#resultsModalTitle"),
  resultsModalCount: $("#resultsModalCount"),
  resultsModalHead: $("#resultsModalHead"),
  resultsModalBody: $("#resultsModalBody"),
  closeResultsModal: $("#closeResultsModal"),
  closeResultsModalBottom: $("#closeResultsModalBottom"),
};

const panelCopy = {
  waybill: {
    title: "Verificação de ID's",
    description:
      "O Chrome será aberto apenas para login e captcha. Após detectar o token, o navegador será fechado e as verificações seguirão em segundo plano.",
    emptyLog: "Os logs vão aparecer aqui quando iniciar.",
  },
  pod: {
    title: "POD Tracking",
    description:
      "Consulta a rota de POD Tracking por ID, lê o primeiro item de data[0].details[0] e monta o preview com Tempo de Digitalização, Tipo de Bipagem, Motivo da Bipagem, Base Responsável e Descrição da Etapa de Bipagem.",
    emptyLog: "Os logs do POD vão aparecer aqui quando iniciar.",
  },
};

let pollTimer = null;
let saveTimer = null;
let lastLogLength = 0;
let lastPodLogLength = 0;
let activePanel = "waybill";
let exportContext = "waybill";
let lastWaybillStatus = null;
let lastPodStatus = null;
let lastResultsSignature = "";
let lastPodResultsSignature = "";
let lastLogsSignature = "";
let lastPodLogsSignature = "";
let latestWaybillResults = [];
let latestPodResults = [];

function restartAnimation(element, className = "animating") {
  if (!element) return;

  element.classList.remove(className);

  // Força reflow para a animação reiniciar quando trocar de painel.
  void element.offsetWidth;

  element.classList.add(className);
}

function sharedUsername() {
  return (activePanel === "pod" ? els.podUsername.value : els.username.value).trim();
}

function sharedPassword() {
  return activePanel === "pod" ? els.podPassword.value : els.password.value;
}

function sharedSavePassword() {
  return activePanel === "pod" ? els.podSavePassword.checked : els.savePassword.checked;
}

function sharedRecreateProfile() {
  return activePanel === "pod" ? els.podRecreateProfile.checked : els.recreateProfile.checked;
}

function currentChromeProfileValue() {
  const mainValue = els.chromeProfile ? els.chromeProfile.value.trim() : "";
  const podValue = els.podChromeProfile ? els.podChromeProfile.value.trim() : "";

  return mainValue || podValue || "Default";
}

function syncChromeProfileFrom(source) {
  if (!els.chromeProfile || !els.podChromeProfile) return;

  if (source === "pod") {
    els.chromeProfile.value = els.podChromeProfile.value;
    return;
  }

  els.podChromeProfile.value = els.chromeProfile.value;
}

function collectPayload() {
  return {
    username: els.username.value.trim(),
    password: els.password.value,
    chrome_profile: currentChromeProfileValue(),
    save_password: els.savePassword.checked,
    recreate_profile: els.recreateProfile.checked,
    waybills: els.waybills ? els.waybills.value : "",
    pod_ids: els.podIds ? els.podIds.value : "",
  };
}
function collectWaybillPayload() {
  return {
    ...collectPayload(),
    username: els.username.value.trim(),
    password: els.password.value,
    save_password: els.savePassword.checked,
    recreate_profile: els.recreateProfile.checked,
    waybills: els.waybills.value,
  };
}

function collectPodPayload() {
  return {
    ...collectPayload(),
    username: els.podUsername.value.trim(),
    password: els.podPassword.value,
    save_password: els.podSavePassword.checked,
    recreate_profile: els.podRecreateProfile.checked,
    pod_ids: els.podIds.value,
  };
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.message || `Erro HTTP ${response.status}`);
  }

  return data;
}

function scheduleSaveConfig() {
  clearTimeout(saveTimer);

  saveTimer = setTimeout(() => {
    saveConfig(false);
  }, 350);
}

async function saveConfig(showToast = false) {
  try {
    await requestJson("/api/config", {
      method: "POST",
      body: JSON.stringify(collectPayload()),
    });

    if (showToast) {
      setSubStatus("Configurações salvas.");
    }
  } catch (error) {
    console.error(error);
  }
}

async function loadConfig() {
  try {
    const config = await requestJson("/api/config");

    els.username.value = config.username || "";
    els.password.value = config.password || "";
    els.savePassword.checked = Boolean(config.save_password);
    els.recreateProfile.checked = Boolean(config.recreate_profile);
    els.waybills.value = config.waybills || "";
    els.chromeProfile.value = config.chrome_profile || "Default";
    if (els.podChromeProfile) {
      els.podChromeProfile.value = config.chrome_profile || "Default";
    }

    els.podUsername.value = config.username || "";
    els.podPassword.value = config.password || "";
    els.podSavePassword.checked = Boolean(config.save_password);
    els.podRecreateProfile.checked = Boolean(config.recreate_profile);
    els.podIds.value = config.pod_ids || "";
  } catch (error) {
    console.error(error);
  }
}

function setSubStatus(text) {
  els.statusSubText.textContent = text;
}

function setStatus(status, running, context = activePanel) {
  const labels = {
    idle: "Aguardando",
    running: "Executando",
    finished: "Finalizado",
    stopped: "Parado",
    error: "Erro",
  };

  if (context === activePanel) {
    els.statusText.textContent = labels[status] || "Aguardando";
  }

  if (context === "pod") {
    els.podStartBtn.disabled = Boolean(running);
    els.podStopBtn.disabled = !running;
  } else {
    els.startBtn.disabled = Boolean(running);
    els.stopBtn.disabled = !running;
  }
}

function updateProgress(current, total, context = "waybill") {
  const safeTotal = Number(total || 0);
  const safeCurrent = Number(current || 0);
  const percent = safeTotal > 0 ? Math.round((safeCurrent / safeTotal) * 100) : 0;

  const label = context === "pod" ? els.podProgressLabel : els.progressLabel;
  const percentEl = context === "pod" ? els.podProgressPercent : els.progressPercent;
  const fill = context === "pod" ? els.podProgressFill : els.progressFill;

  label.textContent = `${safeCurrent} de ${safeTotal}`;
  percentEl.textContent = `${percent}%`;
  fill.style.width = `${Math.min(percent, 100)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderLogs(logs, context = "waybill") {
  const box = context === "pod" ? els.podLogsBox : els.logsBox;
  const emptyText = context === "pod" ? panelCopy.pod.emptyLog : panelCopy.waybill.emptyLog;
  const signature = JSON.stringify(logs || []);

  if (context === "pod") {
    if (signature === lastPodLogsSignature) return;
    lastPodLogsSignature = signature;
  } else {
    if (signature === lastLogsSignature) return;
    lastLogsSignature = signature;
  }

  if (!logs || logs.length === 0) {
    box.innerHTML = `<div class="empty-log static-empty">${emptyText}</div>`;

    if (context === "pod") {
      lastPodLogLength = 0;
    } else {
      lastLogLength = 0;
    }

    return;
  }

  const oldLength = context === "pod" ? lastPodLogLength : lastLogLength;
  const shouldScroll = logs.length !== oldLength;

  if (context === "pod") {
    lastPodLogLength = logs.length;
  } else {
    lastLogLength = logs.length;
  }

  box.innerHTML = logs
    .map((line) => {
      const level = line.level || "info";
      const msg = `[${line.time}] ${line.message}`;

      return `<div class="log-line ${escapeHtml(level)}">${escapeHtml(msg)}</div>`;
    })
    .join("");

  if (shouldScroll) {
    box.scrollTop = box.scrollHeight;
  }
}

function statusPill(status) {
  const safe = String(status || "").toLowerCase();

  if (safe === "ok") {
    return `<span class="status-pill status-ok">OK</span>`;
  }

  if (safe === "aviso") {
    return `<span class="status-pill status-aviso">Aviso</span>`;
  }

  if (safe === "erro") {
    return `<span class="status-pill status-erro">Erro</span>`;
  }

  return `<span class="status-pill">${escapeHtml(status || "-")}</span>`;
}

function renderResults(results) {
  const count = results ? results.length : 0;
  const signature = JSON.stringify(results || []);

  latestWaybillResults = results || [];

  const countText = `${count} registro${count === 1 ? "" : "s"}`;

  if (els.resultsCount.textContent !== countText) {
    els.resultsCount.textContent = countText;
  }

  els.viewResultsBtn.disabled = count === 0;

  if (signature === lastResultsSignature) {
    return;
  }

  lastResultsSignature = signature;

  if (!results || results.length === 0) {
    els.exportBtn.classList.add("disabled");

    els.resultsSummaryBox.innerHTML = `
      <div class="summary-icon">📦</div>
      <strong>Nenhum resultado para visualizar</strong>
      <small>Quando a automação coletar dados, clique em “Ver resultados” para abrir a janela completa.</small>
    `;

    return;
  }

  els.exportBtn.classList.remove("disabled");

  els.resultsSummaryBox.innerHTML = `
    <div class="summary-icon success">✅</div>
    <strong>${countText} coletado${count === 1 ? "" : "s"}</strong>
    <small>Clique em “Ver resultados” para abrir a visualização completa em uma janela separada.</small>
  `;
}

function renderPodResults(results) {
  const count = results ? results.length : 0;
  const signature = JSON.stringify(results || []);

  latestPodResults = results || [];

  const countText = `${count} registro${count === 1 ? "" : "s"}`;

  if (els.podResultsCount.textContent !== countText) {
    els.podResultsCount.textContent = countText;
  }

  els.viewPodResultsBtn.disabled = count === 0;

  if (signature === lastPodResultsSignature) {
    return;
  }

  lastPodResultsSignature = signature;

  if (!results || results.length === 0) {
    els.podExportBtn.classList.add("disabled");

    els.podResultsSummaryBox.innerHTML = `
      <div class="summary-icon">🧾</div>
      <strong>Nenhum resultado POD para visualizar</strong>
      <small>Quando a automação coletar dados, clique em “Ver resultados” para abrir a janela completa.</small>
    `;

    return;
  }

  els.podExportBtn.classList.remove("disabled");

  els.podResultsSummaryBox.innerHTML = `
    <div class="summary-icon success">✅</div>
    <strong>${countText} POD coletado${count === 1 ? "" : "s"}</strong>
    <small>Clique em “Ver resultados” para abrir a visualização completa em uma janela separada.</small>
  `;
}

function openResultsModal(context = "waybill") {
  const isPod = context === "pod";
  const rows = isPod ? latestPodResults : latestWaybillResults;

  if (!rows || rows.length === 0) {
    alert("Não há resultados para visualizar.");
    return;
  }

  els.resultsModalTitle.textContent = isPod
    ? "Resultados POD Tracking"
    : "Resultados Verificação de ID's";

  els.resultsModalCount.textContent = `${rows.length} registro${rows.length === 1 ? "" : "s"}`;

  if (isPod) {
    els.resultsModalHead.innerHTML = `
      <tr>
        <th>ID do pacote</th>
        <th>Tempo de Digitalização</th>
        <th>Tipo de Bipagem</th>
        <th>Motivo da Bipagem</th>
        <th>Base Responsável</th>
        <th>Descrição da Etapa de Bipagem</th>
        <th>Status</th>
        <th>Mensagem</th>
      </tr>
    `;

    els.resultsModalBody.innerHTML = rows
      .map((row) => {
        return `
          <tr class="table-row-enter">
            <td>${escapeHtml(row.waybillNo || "")}</td>
            <td>${escapeHtml(row.scanTime || "")}</td>
            <td>${escapeHtml(row.scanTypeName || "")}</td>
            <td>${escapeHtml(row.remark1 || "")}</td>
            <td>${escapeHtml(row.scanNetworkName || "")}</td>
            <td>${escapeHtml(row.podTemplateContent || "")}</td>
            <td>${statusPill(row.status || "")}</td>
            <td>${escapeHtml(row.message || "")}</td>
          </tr>
        `;
      })
      .join("");
  } else {
    els.resultsModalHead.innerHTML = `
      <tr>
        <th>ID do pacote</th>
        <th>Conteúdo do Pacote</th>
        <th>Valor da NF</th>
        <th>Status</th>
        <th>Mensagem</th>
      </tr>
    `;

    els.resultsModalBody.innerHTML = rows
      .map((row) => {
        return `
          <tr class="table-row-enter">
            <td>${escapeHtml(row.waybillNos || "")}</td>
            <td>${escapeHtml(row.goodsName || "")}</td>
            <td>${escapeHtml(row.insuredAmount || "")}</td>
            <td>${statusPill(row.status || "")}</td>
            <td>${escapeHtml(row.message || "")}</td>
          </tr>
        `;
      })
      .join("");
  }

  els.resultsModal.classList.remove("hidden");
  els.resultsModal.style.display = "flex";
  document.body.classList.add("modal-open");
}

function closeResultsModal() {
  els.resultsModal.classList.add("hidden");
  els.resultsModal.style.display = "none";
  document.body.classList.remove("modal-open");
}

function openModal() {
  els.exportModal.classList.remove("hidden");
  els.exportModal.style.display = "flex";

  const modal = els.exportModal.querySelector(".export-modal");

  if (modal) {
    modal.style.display = "flex";
    modal.style.opacity = "1";
    modal.style.visibility = "visible";
    modal.style.transform = "translateY(0) scale(1)";
  }

  document.body.classList.add("modal-open");
}

function closeModal() {
  els.exportModal.classList.add("hidden");
  els.exportModal.style.display = "none";
  document.body.classList.remove("modal-open");
}

function setExportHeaders(context) {
  if (context === "pod") {
    els.exportModalTitle.textContent = "Preview do XLSX - POD Tracking";
    els.exportPreviewHead.innerHTML = `
      <tr>
        <th>ID do pacote</th>
        <th>Tempo de Digitalização</th>
        <th>Tipo de Bipagem</th>  
        <th>Motivo da Bipagem</th>
        <th>Base Responsável</th>
        <th>Descrição da Etapa de Bipagem</th>
        <th>Status</th>
        <th>Mensagem</th>
      </tr>
    `;
    return;
  }

  els.exportModalTitle.textContent = "Preview do XLSX";
  els.exportPreviewHead.innerHTML = `
    <tr>
      <th>ID do pacote</th>
      <th>Conteúdo do Pacote</th>
      <th>Valor da NF</th>
    </tr>
  `;
}

function renderExportPreview(rows, context = "waybill") {
  const colspan = context === "pod" ? 8 : 3;

  if (!rows || rows.length === 0) {
    els.exportPreviewBody.innerHTML = `
      <tr class="empty-row static-empty">
        <td colspan="${colspan}">Nenhum dado para exportar.</td>
      </tr>
    `;

    return;
  }

  if (context === "pod") {
    els.exportPreviewBody.innerHTML = rows
      .map((row) => {
        return `
          <tr class="table-row-enter">
            <td>${escapeHtml(row.waybillNo || "")}</td>
            <td>${escapeHtml(row.scanTime || "")}</td>
            <td>${escapeHtml(row.scanTypeName || "")}</td>
            <td>${escapeHtml(row.remark1 || "")}</td>
            <td>${escapeHtml(row.scanNetworkName || "")}</td>
            <td>${escapeHtml(row.podTemplateContent || "")}</td>
            <td>${statusPill(row.status || "ok")}</td>
            <td>${escapeHtml(row.message || "")}</td>
          </tr>
        `;
      })
      .join("");

    return;
  }

  els.exportPreviewBody.innerHTML = rows
    .map((row) => {
      return `
        <tr class="table-row-enter">
          <td>${escapeHtml(row.waybillNos || "")}</td>
          <td>${escapeHtml(row.goodsName || "")}</td>
          <td>${escapeHtml(row.insuredAmount || "")}</td>
        </tr>
      `;
    })
    .join("");
}

async function openExportPreview(context = "waybill") {
  try {
    const exportButton = context === "pod" ? els.podExportBtn : els.exportBtn;

    if (exportButton.classList.contains("disabled")) {
      return;
    }

    exportContext = context;
    setExportHeaders(context);

    const url = context === "pod" ? "/api/pod/export/preview" : "/api/export/preview";
    const data = await requestJson(url);

    if (!data.total) {
      alert("Não há resultados para exportar.");
      return;
    }

    els.exportFileName.textContent = data.filename || "-";
    els.exportFolder.textContent = data.folder || "-";
    els.exportTotal.textContent = `${data.total} registro${data.total === 1 ? "" : "s"}`;

    renderExportPreview(data.rows || [], context);
    openModal();
  } catch (error) {
    alert(error.message || "Erro ao carregar preview da exportação.");
  }
}

async function confirmExport() {
  try {
    els.confirmExportBtn.disabled = true;
    els.confirmExportBtn.textContent = "Exportando...";

    const url = exportContext === "pod" ? "/api/pod/export" : "/api/export";

    const data = await requestJson(url, {
      method: "POST",
      body: JSON.stringify({}),
    });

    closeModal();

    alert(
      `XLSX exportado com sucesso!\n\nArquivo: ${data.filename}\nPasta: ${data.path}`
    );

    await pollStatus();
  } catch (error) {
    alert(error.message || "Erro ao exportar XLSX.");
  } finally {
    els.confirmExportBtn.disabled = false;
    els.confirmExportBtn.textContent = "Confirmar exportação";
  }
}

function updateActiveHeader() {
  const copy = panelCopy[activePanel] || panelCopy.waybill;
  els.heroTitle.textContent = copy.title;
  els.heroDescription.textContent = copy.description;

  const state = activePanel === "pod" ? lastPodStatus : lastWaybillStatus;

  if (!state) {
    els.statusText.textContent = "Aguardando";
    els.statusSubText.textContent = "Nenhuma execução iniciada.";
    return;
  }

  renderTopStatus(state, activePanel);
}

function renderTopStatus(data, context) {
  if (context !== activePanel) return;

  setStatus(data.status, data.running, context);

  if (data.running) {
    setSubStatus(`Consultando ${data.current || 0} de ${data.total || 0}.`);
  } else if (data.status === "finished") {
    setSubStatus("Execução concluída.");
  } else if (data.status === "error") {
    setSubStatus("A execução terminou com erro. Veja os logs.");
  } else if (data.status === "stopped") {
    setSubStatus("Execução interrompida.");
  } else {
    setSubStatus("Nenhuma execução iniciada.");
  }
}

async function pollStatus() {
  try {
    const [waybillData, podData] = await Promise.all([
      requestJson("/api/status"),
      requestJson("/api/pod/status"),
    ]);

    lastWaybillStatus = waybillData;
    lastPodStatus = podData;

    setStatus(waybillData.status, waybillData.running, "waybill");
    updateProgress(waybillData.current, waybillData.total, "waybill");
    renderLogs(waybillData.logs || [], "waybill");
    renderResults(waybillData.results || []);

    setStatus(podData.status, podData.running, "pod");
    updateProgress(podData.current, podData.total, "pod");
    renderLogs(podData.logs || [], "pod");
    renderPodResults(podData.results || []);

    renderTopStatus(activePanel === "pod" ? podData : waybillData, activePanel);
  } catch (error) {
    console.error(error);
  }
}

function startPolling() {
  if (pollTimer) return;

  pollStatus();

  pollTimer = setInterval(pollStatus, 800);
}

async function startAutomation() {
  try {
    syncCredentialsFrom("waybill");
    await saveConfig(false);

    els.startBtn.disabled = true;
    els.stopBtn.disabled = false;

    setStatus("running", true, "waybill");
    setSubStatus("Iniciando Chrome e perfil clonado...");

    await requestJson("/api/start", {
      method: "POST",
      body: JSON.stringify(collectWaybillPayload()),
    });

    startPolling();
  } catch (error) {
    alert(error.message || "Erro ao iniciar automação.");
    els.startBtn.disabled = false;
    els.stopBtn.disabled = true;
  }
}

async function startPodAutomation() {
  try {
    syncCredentialsFrom("pod");
    await saveConfig(false);

    els.podStartBtn.disabled = true;
    els.podStopBtn.disabled = false;

    setStatus("running", true, "pod");
    setSubStatus("Iniciando Chrome e perfil clonado...");

    await requestJson("/api/pod/start", {
      method: "POST",
      body: JSON.stringify(collectPodPayload()),
    });

    startPolling();
  } catch (error) {
    alert(error.message || "Erro ao iniciar POD Tracking.");
    els.podStartBtn.disabled = false;
    els.podStopBtn.disabled = true;
  }
}

async function stopAutomation() {
  try {
    els.stopBtn.disabled = true;
    setSubStatus("Solicitando parada...");

    await requestJson("/api/stop", {
      method: "POST",
      body: JSON.stringify({}),
    });

    startPolling();
  } catch (error) {
    alert(error.message || "Erro ao parar automação.");
  }
}

async function stopPodAutomation() {
  try {
    els.podStopBtn.disabled = true;
    setSubStatus("Solicitando parada...");

    await requestJson("/api/pod/stop", {
      method: "POST",
      body: JSON.stringify({}),
    });

    startPolling();
  } catch (error) {
    alert(error.message || "Erro ao parar POD Tracking.");
  }
}

function clearLogsVisual(context = "waybill") {
  const box = context === "pod" ? els.podLogsBox : els.logsBox;
  box.innerHTML = `<div class="empty-log">Visual limpo. Os logs reais continuam no estado da execução.</div>`;
}

function setUpdateStatus(text, isError = false) {
  if (!els.updateStatus) return;
  els.updateStatus.textContent = text;
  els.updateStatus.classList.toggle("error", Boolean(isError));
}

async function checkForUpdate() {
  if (!els.checkUpdateBtn) return;

  try {
    els.checkUpdateBtn.disabled = true;
    els.checkUpdateBtn.textContent = "Verificando...";
    els.applyUpdateBtn.disabled = true;
    setUpdateStatus("Consultando última versão no GitHub...");

    const data = await requestJson("/api/update/check");

    setUpdateStatus(data.message || "Verificação concluída.");

    if (data.has_update) {
      els.applyUpdateBtn.disabled = false;
      els.applyUpdateBtn.dataset.latestVersion = data.latest_version || "";
    }
  } catch (error) {
    setUpdateStatus(error.message || "Erro ao verificar atualização.", true);
    alert(error.message || "Erro ao verificar atualização.");
  } finally {
    els.checkUpdateBtn.disabled = false;
    els.checkUpdateBtn.textContent = "Verificar atualização";
  }
}

async function applyUpdate() {
  const latest = els.applyUpdateBtn?.dataset?.latestVersion || "";

  const ok = confirm(
    latest
      ? `Atualizar o sistema para a versão v${latest}?\n\nO programa será fechado e aberto novamente ao terminar.`
      : "Atualizar o sistema agora?\n\nO programa será fechado e aberto novamente ao terminar."
  );

  if (!ok) return;

  try {
    await saveConfig(false);

    els.applyUpdateBtn.disabled = true;
    els.checkUpdateBtn.disabled = true;
    els.applyUpdateBtn.textContent = "Abrindo atualizador...";
    setUpdateStatus("Abrindo Atualizador.exe. O sistema será fechado em seguida...");

    await requestJson("/api/update/apply", {
      method: "POST",
      body: JSON.stringify({}),
    });

    setUpdateStatus("Atualizador aberto. Aguarde a conclusão na janela separada.");
  } catch (error) {
    els.applyUpdateBtn.disabled = false;
    els.checkUpdateBtn.disabled = false;
    els.applyUpdateBtn.textContent = "Atualizar sistema";
    setUpdateStatus(error.message || "Erro ao iniciar atualização.", true);
    alert(error.message || "Erro ao iniciar atualização.");
  }
}

function syncCredentialsFrom(source) {
  if (source === "pod") {
    els.username.value = els.podUsername.value;
    els.password.value = els.podPassword.value;
    els.savePassword.checked = els.podSavePassword.checked;
    els.recreateProfile.checked = els.podRecreateProfile.checked;
    return;
  }

  els.podUsername.value = els.username.value;
  els.podPassword.value = els.password.value;
  els.podSavePassword.checked = els.savePassword.checked;
  els.podRecreateProfile.checked = els.recreateProfile.checked;
}

function switchPanel(panel) {
  activePanel = panel === "pod" ? "pod" : "waybill";

  els.sidebarLinks.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === activePanel);
  });

  els.panelWaybill.classList.toggle("active", activePanel === "waybill");
  els.panelPod.classList.toggle("active", activePanel === "pod");

  updateActiveHeader();

  const activeEl = activePanel === "pod" ? els.panelPod : els.panelWaybill;

  restartAnimation(activeEl, "panel-animating");
  restartAnimation(document.querySelector(".hero"), "hero-animating");
}

function setupEvents() {
  [
    els.username,
    els.password,
    els.chromeProfile,
    els.waybills,
    els.savePassword,
    els.recreateProfile,
  ].forEach((el) => {
    if (!el) return;

    el.addEventListener("input", () => {
      syncCredentialsFrom("waybill");
      syncChromeProfileFrom("waybill");
      scheduleSaveConfig();
    });

    el.addEventListener("change", () => {
      syncCredentialsFrom("waybill");
      syncChromeProfileFrom("waybill");
      scheduleSaveConfig();
    });
  });

  [
    els.podUsername,
    els.podPassword,
    els.podChromeProfile,
    els.podIds,
    els.podSavePassword,
    els.podRecreateProfile,
  ].forEach((el) => {
    if (!el) return;

    el.addEventListener("input", () => {
      syncCredentialsFrom("pod");
      syncChromeProfileFrom("pod");
      scheduleSaveConfig();
    });

    el.addEventListener("change", () => {
      syncCredentialsFrom("pod");
      syncChromeProfileFrom("pod");
      scheduleSaveConfig();
    });
  });

  els.sidebarLinks.forEach((button) => {
    button.addEventListener("click", () => switchPanel(button.dataset.panel));
  });

  els.startBtn.addEventListener("click", startAutomation);
  els.stopBtn.addEventListener("click", stopAutomation);
  els.clearLogsBtn.addEventListener("click", () => clearLogsVisual("waybill"));

  els.podStartBtn.addEventListener("click", startPodAutomation);
  els.podStopBtn.addEventListener("click", stopPodAutomation);
  els.podClearLogsBtn.addEventListener("click", () => clearLogsVisual("pod"));

  if (els.checkUpdateBtn) {
    els.checkUpdateBtn.addEventListener("click", checkForUpdate);
  }

  if (els.applyUpdateBtn) {
    els.applyUpdateBtn.addEventListener("click", applyUpdate);
  }

  els.togglePassword.addEventListener("click", () => {
    const isPassword = els.password.type === "password";
    els.password.type = isPassword ? "text" : "password";
  });

  els.togglePodPassword.addEventListener("click", () => {
    const isPassword = els.podPassword.type === "password";
    els.podPassword.type = isPassword ? "text" : "password";
  });

  els.exportBtn.addEventListener("click", () => openExportPreview("waybill"));
  els.podExportBtn.addEventListener("click", () => openExportPreview("pod"));
  els.closeExportModal.addEventListener("click", closeModal);
  els.cancelExportBtn.addEventListener("click", closeModal);
  els.confirmExportBtn.addEventListener("click", confirmExport);

  els.exportModal.addEventListener("click", (event) => {
    if (event.target === els.exportModal) {
      closeModal();
    }
  });

  els.viewResultsBtn.addEventListener("click", () => openResultsModal("waybill"));
  els.viewPodResultsBtn.addEventListener("click", () => openResultsModal("pod"));

  els.closeResultsModal.addEventListener("click", closeResultsModal);
  els.closeResultsModalBottom.addEventListener("click", closeResultsModal);

  els.resultsModal.addEventListener("click", (event) => {
    if (event.target === els.resultsModal) {
      closeResultsModal();
    }
  });
}

async function boot() {
  document.body.classList.add("app-loading");

  setupEvents();

  await loadConfig();
  await pollStatus();

  startPolling();

  requestAnimationFrame(() => {
    document.body.classList.remove("app-loading");
    document.body.classList.add("app-ready");
  });
}

boot();