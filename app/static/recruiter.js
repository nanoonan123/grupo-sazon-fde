(() => {
  const filters = document.querySelector("#application-filters");
  if (!filters) return;

  const rowsElement = document.querySelector("#application-rows");
  const resultCount = document.querySelector("#result-count");
  const pageLabel = document.querySelector("#page-label");
  const previousPage = document.querySelector("#previous-page");
  const nextPage = document.querySelector("#next-page");
  const metricsStatus = document.querySelector("#metrics-status");
  const dropoffList = document.querySelector("#dropoff-list");
  const dialog = document.querySelector("#detail-dialog");
  const detailTitle = document.querySelector("#detail-title");
  const detailContent = document.querySelector("#detail-content");
  const pageSize = 20;
  let page = 1;
  let total = 0;

  const labels = {
    status: {
      in_progress: ["En curso", "In progress"],
      qualified: ["Cualificado", "Qualified"],
      disqualified: ["No cualificado", "Disqualified"],
      needs_review: ["Revisión", "Needs review"],
      incomplete: ["Detenido", "Stopped"],
      deleted: ["Eliminado", "Deleted"],
    },
    stage: {
      consent: ["Consentimiento", "Consent"],
      full_name: ["Nombre", "Full name"],
      driver_license: ["Permiso", "Driver's license"],
      service_area: ["Zona", "Service area"],
      availability: ["Disponibilidad", "Availability"],
      preferred_schedule: ["Horario", "Schedule"],
      delivery_experience_years: ["Experiencia", "Experience"],
      start_date: ["Fecha de inicio", "Start date"],
      complete: ["Completado", "Complete"],
      not_started: ["No iniciado", "Not started"],
    },
  };

  function english() {
    return document.documentElement.lang === "en";
  }

  function localized(pair) {
    return pair?.[english() ? 1 : 0] || "—";
  }

  function el(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined && content !== null) element.textContent = content;
    return element;
  }

  async function getJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
  }

  function metricValue(name, value) {
    if (["completion_rate", "qualification_rate"].includes(name)) {
      return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    }
    if (name === "average_completed_screening_duration_seconds") {
      if (!value) return "0 s";
      return value >= 60 ? `${(value / 60).toFixed(1)} min` : `${value.toFixed(0)} s`;
    }
    if (name === "p50_provider_latency_ms") return `${value || 0} ms`;
    return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function renderMetrics(metrics) {
    document.querySelectorAll("[data-metric]").forEach((node) => {
      const name = node.dataset.metric;
      node.textContent = metricValue(name, metrics[name]);
    });
    dropoffList.replaceChildren();
    const entries = Object.entries(metrics.drop_off_by_current_stage);
    if (!entries.length) {
      dropoffList.append(el("p", "muted", english() ? "No non-completions." : "Sin casos no finalizados."));
    } else {
      const maximum = Math.max(...entries.map(([, count]) => count));
      entries.forEach(([stage, count]) => {
        const row = el("div", "dropoff-row");
        const copy = el("div", "dropoff-copy");
        copy.append(el("span", "", localized(labels.stage[stage]) || stage), el("strong", "", String(count)));
        const track = el("div", "mini-track");
        const fill = el("span");
        fill.style.width = `${(count / maximum) * 100}%`;
        track.append(fill);
        row.append(copy, track);
        dropoffList.append(row);
      });
    }
    metricsStatus.textContent = english() ? "Updated from database" : "Actualizado desde la base de datos";
  }

  async function loadMetrics() {
    try {
      renderMetrics(await getJson("/api/recruiter/metrics"));
    } catch (_error) {
      metricsStatus.textContent = english() ? "Could not load metrics" : "No se pudieron cargar las métricas";
    }
  }

  function statusPill(value) {
    return el("span", `status-pill status-pill--${value || "pending"}`, localized(labels.status[value]) || value || "—");
  }

  function applicationRow(item) {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    const detailButton = el("button", "candidate-link", item.name || (english() ? "Unnamed candidate" : "Sin nombre"));
    detailButton.type = "button";
    detailButton.addEventListener("click", () => openDetail(item.application_id));
    nameCell.append(detailButton, el("small", "", item.phone_number));
    row.append(nameCell);
    row.append(el("td", "mono", item.external_application_id));
    row.append(el("td", "", item.location || "—"));
    row.append(el("td", "", `${item.progress_collected}/${item.progress_total}`));
    const statusCell = document.createElement("td");
    statusCell.append(statusPill(item.status));
    row.append(statusCell);
    const outcomeCell = document.createElement("td");
    outcomeCell.append(statusPill(item.outcome));
    row.append(outcomeCell);
    row.append(el("td", "nowrap", new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.updated_at))));
    return row;
  }

  async function loadApplications() {
    rowsElement.replaceChildren();
    const loadingRow = document.createElement("tr");
    const loadingCell = el("td", "empty-cell", english() ? "Loading applications…" : "Cargando candidaturas…");
    loadingCell.colSpan = 7;
    loadingRow.append(loadingCell);
    rowsElement.append(loadingRow);
    const formData = new FormData(filters);
    const parameters = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    for (const [key, value] of formData.entries()) if (value) parameters.set(key, value);
    try {
      const payload = await getJson(`/api/recruiter/applications?${parameters}`);
      total = payload.total;
      rowsElement.replaceChildren();
      if (!payload.items.length) {
        const emptyRow = document.createElement("tr");
        const emptyCell = el("td", "empty-cell", english() ? "No matching applications." : "No hay candidaturas con estos filtros.");
        emptyCell.colSpan = 7;
        emptyRow.append(emptyCell);
        rowsElement.append(emptyRow);
      } else {
        payload.items.forEach((item) => rowsElement.append(applicationRow(item)));
      }
      resultCount.textContent = english() ? `${total} applications` : `${total} candidaturas`;
      pageLabel.textContent = `${page} / ${Math.max(1, Math.ceil(total / pageSize))}`;
      previousPage.disabled = page === 1;
      nextPage.disabled = page * pageSize >= total;
    } catch (_error) {
      rowsElement.replaceChildren();
      const errorRow = document.createElement("tr");
      const errorCell = el("td", "empty-cell", english() ? "Could not load applications." : "No se pudieron cargar las candidaturas.");
      errorCell.colSpan = 7;
      errorRow.append(errorCell);
      rowsElement.append(errorRow);
    }
  }

  function addDefinitionList(parent, values) {
    const list = el("dl", "detail-grid");
    values.forEach(([term, value]) => {
      const wrapper = document.createElement("div");
      wrapper.append(el("dt", "", term), el("dd", "", value ?? "—"));
      list.append(wrapper);
    });
    parent.append(list);
  }

  function detailSection(title) {
    const section = document.createElement("section");
    section.append(el("h3", "", title));
    detailContent.append(section);
    return section;
  }

  function readable(value) {
    if (Array.isArray(value)) return value.join(", ") || "—";
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function renderDetail(payload) {
    const item = payload.application;
    detailTitle.textContent = item.name || (english() ? "Unnamed candidate" : "Candidatura sin nombre");
    detailContent.replaceChildren();
    const overview = detailSection(english() ? "Outcome and progress" : "Resultado y progreso");
    addDefinitionList(overview, [
      ["Application ID", item.application_id],
      [english() ? "External ID" : "ID externo", item.external_application_id],
      [english() ? "Status" : "Estado", localized(labels.status[item.status]) || item.status],
      [english() ? "Outcome" : "Resultado", localized(labels.status[item.outcome]) || item.outcome],
      [english() ? "Progress" : "Progreso", `${item.progress_collected}/${item.progress_total}`],
      [english() ? "Deterministic reason" : "Motivo determinista", payload.deterministic_reason],
      [english() ? "Escalation fields" : "Campos de escalado", payload.escalation_fields.join(", ") || "—"],
    ]);

    const fields = detailSection(english() ? "Structured screening fields" : "Campos estructurados");
    const fieldLabels = {
      full_name: ["Nombre completo", "Full name"], language: ["Idioma conversacional", "Conversation language"], driver_license: ["Permiso de conducir", "Driver's license"], location_country: ["País canónico", "Canonical country"], location_city: ["Ciudad", "City"], location_zone: ["Zona", "Zone"], availability: ["Disponibilidad", "Availability"], preferred_schedule: ["Horario preferido", "Preferred schedule"], delivery_experience_years: ["Años de reparto", "Delivery years"], delivery_platforms: ["Plataformas", "Platforms"], start_date: ["Fecha de inicio", "Start date"],
    };
    addDefinitionList(fields, Object.entries(fieldLabels).map(([key, pair]) => [localized(pair), readable(payload.screening_data[key])]));

    const summaries = detailSection(english() ? "Summaries" : "Resúmenes");
    summaries.append(el("h4", "", english() ? "Latest candidate-facing message" : "Último mensaje mostrado a la candidatura"), el("p", "summary-box", payload.candidate_summary || "—"), el("h4", "", english() ? "Final screening summary" : "Resumen final del screening"), el("p", "summary-box", payload.final_summary || "—"));

    const provider = detailSection(english() ? "Provider operations" : "Operación del proveedor");
    addDefinitionList(provider, [
      ["Provider", payload.provider.provider], ["Model", payload.provider.model], [english() ? "Latest latency" : "Última latencia", payload.provider.last_latency_ms === null ? "—" : `${payload.provider.last_latency_ms} ms`], ["P50", `${payload.provider.p50_latency_ms} ms`], [english() ? "Recoverable errors" : "Errores recuperables", payload.provider.recoverable_error_count], [english() ? "Latest error code" : "Último código de error", payload.provider.latest_recoverable_error_code],
    ]);

    const transcript = detailSection(english() ? "Ordered transcript" : "Transcripción ordenada");
    const conversation = el("div", "detail-transcript");
    payload.transcript.forEach((message) => {
      const bubble = el("article", `transcript-message transcript-message--${message.role}`);
      bubble.append(el("strong", "", message.role === "assistant" ? (english() ? "Assistant" : "Asistente") : (english() ? "Candidate" : "Candidato/a")), el("p", "", message.content), el("time", "", new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(message.created_at))));
      conversation.append(bubble);
    });
    if (!payload.transcript.length) conversation.append(el("p", "muted", english() ? "No messages yet." : "Todavía no hay mensajes."));
    transcript.append(conversation);
  }

  async function openDetail(applicationId) {
    detailTitle.textContent = english() ? "Loading…" : "Cargando…";
    detailContent.replaceChildren(el("p", "muted", english() ? "Loading detail…" : "Cargando detalle…"));
    dialog.showModal();
    try {
      renderDetail(await getJson(`/api/recruiter/applications/${encodeURIComponent(applicationId)}`));
    } catch (_error) {
      detailContent.replaceChildren(el("p", "muted", english() ? "Could not load detail." : "No se pudo cargar el detalle."));
    }
  }

  filters.addEventListener("submit", (event) => { event.preventDefault(); page = 1; loadApplications(); });
  previousPage.addEventListener("click", () => { if (page > 1) { page -= 1; loadApplications(); } });
  nextPage.addEventListener("click", () => { if (page * pageSize < total) { page += 1; loadApplications(); } });
  document.querySelector("#close-detail").addEventListener("click", () => dialog.close());
  document.addEventListener("ui-language-change", () => { loadMetrics(); loadApplications(); });

  loadMetrics();
  loadApplications();
})();
