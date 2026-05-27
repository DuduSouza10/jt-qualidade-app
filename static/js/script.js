const $ = (selector) => document.querySelector(selector);

const els = {
  username: $("#username"),
  password: $("#password"),
  savePassword: $("#savePassword"),
  recreateProfile: $("#recreateProfile"),
  waybills: $("#waybills"),

  startBtn: $("#startBtn"),
  stopBtn: $("#stopBtn"),
  exportBtn: $("#exportBtn"),
  checkUpdateBtn: $("#checkUpdateBtn"),
  applyUpdateBtn: $("#applyUpdateBtn"),
  updateStatus: $("#updateStatus"),
  togglePassword: $("#togglePassword"),
  clearLogsBtn: $("#clearLogsBtn"),

  statusText: $("#statusText"),
  statusSubText: $("#statusSubText"),

  progressLabel: $("#progressLabel"),
  progressPercent: $("#progressPercent"),
  progressFill: $("#progressFill"),

  logsBox: $("#logsBox"),
  resultsBody: $("#resultsBody"),
  resultsCount: $("#resultsCount"),

  exportModal: $("#exportModal"),
  closeExportModal: $("#closeExportModal"),
  cancelExportBtn: $("#cancelExportBtn"),
  confirmExportBtn: $("#confirmExportBtn"),
  exportFileName: $("#exportFileName"),
  exportFolder: $("#exportFolder"),
  exportTotal: $("#exportTotal"),
  exportPreviewBody: $("#exportPreviewBody"),
};

let pollTimer = null;
let saveTimer = null;
let lastLogLength = 0;

function collectPayload() {
  return {
    username: els.username.value.trim(),
    password: els.password.value,
    save_password: els.savePassword.checked,
    recreate_profile: els.recreateProfile.checked,
    waybills: els.waybills.value,
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
  } catch (error) {
    console.error(error);
  }
}

function setSubStatus(text) {
  els.statusSubText.textContent = text;
}

function setStatus(status, running) {
  const labels = {
    idle: "Aguardando",
    running: "Executando",
    finished: "Finalizado",
    stopped: "Parado",
    error: "Erro",
  };

  els.statusText.textContent = labels[status] || "Aguardando";

  if (running) {
    els.startBtn.disabled = true;
    els.stopBtn.disabled = false;
  } else {
    els.startBtn.disabled = false;
    els.stopBtn.disabled = true;
  }
}

function updateProgress(current, total) {
  const safeTotal = Number(total || 0);
  const safeCurrent = Number(current || 0);
  const percent = safeTotal > 0 ? Math.round((safeCurrent / safeTotal) * 100) : 0;

  els.progressLabel.textContent = `${safeCurrent} de ${safeTotal}`;
  els.progressPercent.textContent = `${percent}%`;
  els.progressFill.style.width = `${Math.min(percent, 100)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderLogs(logs) {
  if (!logs || logs.length === 0) {
    els.logsBox.innerHTML = `<div class="empty-log">Os logs vão aparecer aqui quando iniciar.</div>`;
    lastLogLength = 0;
    return;
  }

  const shouldScroll = logs.length !== lastLogLength;
  lastLogLength = logs.length;

  els.logsBox.innerHTML = logs
    .map((line) => {
      const level = line.level || "info";
      const msg = `[${line.time}] ${line.message}`;

      return `<div class="log-line ${escapeHtml(level)}">${escapeHtml(msg)}</div>`;
    })
    .join("");

  if (shouldScroll) {
    els.logsBox.scrollTop = els.logsBox.scrollHeight;
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

  els.resultsCount.textContent = `${count} registro${count === 1 ? "" : "s"}`;

  if (!results || results.length === 0) {
    els.resultsBody.innerHTML = `
      <tr class="empty-row">
        <td colspan="5">Nenhum dado coletado ainda.</td>
      </tr>
    `;

    els.exportBtn.classList.add("disabled");
    return;
  }

  els.exportBtn.classList.remove("disabled");

  els.resultsBody.innerHTML = results
    .map((row) => {
      return `
        <tr>
          <td>${escapeHtml(row.waybillNos)}</td>
          <td>${escapeHtml(row.goodsName)}</td>
          <td>${escapeHtml(row.insuredAmount)}</td>
          <td>${statusPill(row.status)}</td>
          <td>${escapeHtml(row.message)}</td>
        </tr>
      `;
    })
    .join("");
}

function openModal() {
  els.exportModal.classList.remove("hidden");
}

function closeModal() {
  els.exportModal.classList.add("hidden");
}

function renderExportPreview(rows) {
  if (!rows || rows.length === 0) {
    els.exportPreviewBody.innerHTML = `
      <tr class="empty-row">
        <td colspan="3">Nenhum dado para exportar.</td>
      </tr>
    `;

    return;
  }

  els.exportPreviewBody.innerHTML = rows
    .map((row) => {
      return `
        <tr>
          <td>${escapeHtml(row.waybillNos)}</td>
          <td>${escapeHtml(row.goodsName)}</td>
          <td>${escapeHtml(row.insuredAmount)}</td>
        </tr>
      `;
    })
    .join("");
}

async function openExportPreview() {
  try {
    if (els.exportBtn.classList.contains("disabled")) {
      return;
    }

    const data = await requestJson("/api/export/preview");

    if (!data.total) {
      alert("Não há resultados para exportar.");
      return;
    }

    els.exportFileName.textContent = data.filename || "-";
    els.exportFolder.textContent = data.folder || "-";
    els.exportTotal.textContent = `${data.total} registro${data.total === 1 ? "" : "s"}`;

    renderExportPreview(data.rows || []);
    openModal();

  } catch (error) {
    alert(error.message || "Erro ao carregar preview da exportação.");
  }
}

async function confirmExport() {
  try {
    els.confirmExportBtn.disabled = true;
    els.confirmExportBtn.textContent = "Exportando...";

    const data = await requestJson("/api/export", {
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

async function pollStatus() {
  try {
    const data = await requestJson("/api/status");

    setStatus(data.status, data.running);
    updateProgress(data.current, data.total);
    renderLogs(data.logs || []);
    renderResults(data.results || []);

    if (data.running) {
      setSubStatus(`Consultando ${data.current || 0} de ${data.total || 0}.`);
    } else if (data.status === "finished") {
      setSubStatus("Execução concluída.");
    } else if (data.status === "error") {
      setSubStatus("A execução terminou com erro. Veja os logs.");
    } else if (data.status === "stopped") {
      setSubStatus("Execução interrompida.");
    }

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
    await saveConfig(false);

    els.startBtn.disabled = true;
    els.stopBtn.disabled = false;

    setStatus("running", true);
    setSubStatus("Iniciando Chrome e perfil clonado...");

    await requestJson("/api/start", {
      method: "POST",
      body: JSON.stringify(collectPayload()),
    });

    startPolling();
  } catch (error) {
    alert(error.message || "Erro ao iniciar automação.");
    els.startBtn.disabled = false;
    els.stopBtn.disabled = true;
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

function clearLogsVisual() {
  els.logsBox.innerHTML = `<div class="empty-log">Visual limpo. Os logs reais continuam no estado da execução.</div>`;
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

function setupEvents() {
  [
    els.username,
    els.password,
    els.waybills,
    els.savePassword,
    els.recreateProfile,
  ].forEach((el) => {
    el.addEventListener("input", scheduleSaveConfig);
    el.addEventListener("change", scheduleSaveConfig);
  });

  els.startBtn.addEventListener("click", startAutomation);
  els.stopBtn.addEventListener("click", stopAutomation);
  els.clearLogsBtn.addEventListener("click", clearLogsVisual);

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

  els.exportBtn.addEventListener("click", openExportPreview);
  els.closeExportModal.addEventListener("click", closeModal);
  els.cancelExportBtn.addEventListener("click", closeModal);
  els.confirmExportBtn.addEventListener("click", confirmExport);

  els.exportModal.addEventListener("click", (event) => {
    if (event.target === els.exportModal) {
      closeModal();
    }
  });
}

async function boot() {
  setupEvents();

  await loadConfig();
  await pollStatus();

  startPolling();
}

boot();