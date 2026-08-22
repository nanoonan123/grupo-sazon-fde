(() => {
  const app = document.querySelector("#candidate-app");
  if (!app) return;

  const conversationId = app.dataset.conversationId;
  const list = document.querySelector("#message-list");
  const form = document.querySelector("#message-form");
  const input = document.querySelector("#message-input");
  const sendButton = form.querySelector("button[type='submit']");
  const typing = document.querySelector("#typing-indicator");
  const networkBanner = document.querySelector("#network-banner");
  const terminalBanner = document.querySelector("#terminal-banner");
  const bookingPanel = document.querySelector("#booking-panel");
  const retryButton = document.querySelector("#retry-button");
  const progressValue = document.querySelector("#progress-value");
  const progressFill = document.querySelector("#progress-fill");
  const progressTrack = document.querySelector(".progress-track");

  const terminalCopy = {
    qualified: ["Screening completado. El equipo de selección revisará los próximos pasos.", "Screening complete. The recruiting team will review next steps."],
    disqualified: ["El screening ha finalizado. Gracias por tu tiempo.", "The screening has ended. Thank you for your time."],
    needs_review: ["Tu información pasará a revisión del equipo de selección.", "Your information will be reviewed by the recruiting team."],
    stopped: ["Has detenido el screening. Tu historial queda guardado.", "You stopped the screening. Your history remains saved."],
    incomplete: ["Has detenido el screening. Tu historial queda guardado.", "You stopped the screening. Your history remains saved."],
    deleted: ["La solicitud de eliminación ha quedado registrada.", "Your deletion request has been recorded."],
  };

  function uiText(pair) {
    return pair[document.documentElement.lang === "en" ? 1 : 0];
  }

  function scrollToLatest() {
    list.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  function appendMessage(message) {
    if (message.message_id && document.querySelector(`[data-message-id="${CSS.escape(message.message_id)}"]`)) return;
    const row = document.createElement("div");
    row.className = `message-row message-row--${message.role}`;
    if (message.role === "assistant") {
      const avatar = document.createElement("img");
      avatar.className = "message-avatar";
      avatar.src = "/static/logo.svg";
      avatar.alt = "";
      avatar.width = 28;
      avatar.height = 28;
      row.append(avatar);
    }
    const article = document.createElement("article");
    article.className = `message message--${message.role}`;
    if (message.message_id) article.dataset.messageId = message.message_id;
    const accessibleRole = document.createElement("span");
    accessibleRole.className = "sr-only";
    accessibleRole.textContent = message.role === "assistant" ? "Asistente" : "Candidato/a";
    const content = document.createElement("p");
    content.textContent = message.content;
    const timestamp = document.createElement("time");
    const createdAt = message.created_at || new Date().toISOString();
    timestamp.dateTime = createdAt;
    timestamp.textContent = new Intl.DateTimeFormat(document.documentElement.lang, { hour: "2-digit", minute: "2-digit" }).format(new Date(createdAt));
    article.append(accessibleRole, content, timestamp);
    row.append(article);
    list.append(row);
    scrollToLatest();
  }

  function setBusy(busy) {
    const terminal = app.dataset.status !== "in_progress";
    input.disabled = busy || terminal;
    sendButton.disabled = busy || terminal;
    typing.hidden = !busy;
    app.setAttribute("aria-busy", String(busy));
    if (busy) scrollToLatest();
  }

  function updateProgress(progress) {
    progressValue.textContent = `${progress.collected_fields}/${progress.total_fields}`;
    const percentage = progress.total_fields ? (progress.collected_fields / progress.total_fields) * 100 : 0;
    progressFill.style.width = `${percentage}%`;
    progressTrack.setAttribute("aria-valuenow", String(progress.collected_fields));
    progressTrack.setAttribute("aria-valuemax", String(progress.total_fields));
    app.dataset.stage = progress.current_stage;
  }

  function updateTerminal(status, outcome) {
    app.dataset.status = status;
    const displayOutcome = outcome === "incomplete" ? "stopped" : (outcome || status);
    app.dataset.outcome = displayOutcome || "";
    const copy = terminalCopy[displayOutcome];
    terminalBanner.hidden = !copy;
    if (copy) terminalBanner.textContent = uiText(copy);
    const terminal = status !== "in_progress";
    input.disabled = terminal;
    sendButton.disabled = terminal;
    document.querySelector("#open-voice")?.toggleAttribute("hidden", terminal);
    if (displayOutcome === "qualified") loadInterviewBooking();
  }

  function bookingText(booking) {
    const options = { weekday: "long", year: "numeric", month: "long", day: "numeric", timeZone: booking.timezone };
    const date = new Intl.DateTimeFormat(document.documentElement.lang, options).format(new Date(booking.starts_at_utc));
    const time = new Intl.DateTimeFormat(document.documentElement.lang, { hour: "2-digit", minute: "2-digit", timeZone: booking.timezone }).format(new Date(booking.starts_at_utc));
    return { date, time };
  }

  function showBookingConfirmation(booking) {
    const { date, time } = bookingText(booking);
    bookingPanel.hidden = false;
    bookingPanel.textContent = document.documentElement.lang === "en"
      ? `Interview reserved for ${date} at ${time} (${booking.timezone}). Grupo Sazón's recruitment team will contact you at that time.`
      : `Entrevista reservada para el ${date} a las ${time} (${booking.timezone}). El equipo de selección de Grupo Sazón contactará contigo en ese horario.`;
  }

  function renderBookingSelector(slots) {
    bookingPanel.hidden = false;
    bookingPanel.replaceChildren();
    const prompt = document.createElement("strong");
    prompt.textContent = document.documentElement.lang === "en" ? "Choose a time for the recruiting team to contact you." : "Elige una hora para que el equipo de selección contacte contigo.";
    const select = document.createElement("select");
    slots.forEach((slot) => {
      const option = document.createElement("option");
      const { date, time } = bookingText(slot);
      option.value = slot.starts_at_utc;
      option.textContent = `${date} · ${time} (${slot.timezone})`;
      select.append(option);
    });
    const button = document.createElement("button");
    button.className = "primary-button";
    button.type = "button";
    button.textContent = document.documentElement.lang === "en" ? "Reserve interview" : "Reservar entrevista";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const booking = await request(`/api/conversations/${encodeURIComponent(conversationId)}/interview-booking`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot_starts_at_utc: select.value }) });
        showBookingConfirmation(booking);
      } catch (_error) {
        button.disabled = false;
        bookingPanel.append(document.createTextNode(document.documentElement.lang === "en" ? " That slot is no longer available; please reload." : " Ese horario ya no está disponible; recarga la página."));
      }
    });
    bookingPanel.append(prompt, select, button);
  }

  async function loadInterviewBooking() {
    if (app.dataset.outcome !== "qualified" || bookingPanel.dataset.loaded === "true") return;
    bookingPanel.dataset.loaded = "true";
    try {
      const payload = await request(`/api/conversations/${encodeURIComponent(conversationId)}/interview-slots`);
      if (payload.booking) showBookingConfirmation(payload.booking);
      else if (payload.slots.length) renderBookingSelector(payload.slots);
    } catch (_error) {
      bookingPanel.dataset.loaded = "";
    }
  }

  function applyResponse(payload) {
    if (payload.selected_language) {
      app.dataset.uiLanguage = payload.selected_language;
      window.grupoSazonApplyLanguage?.(payload.selected_language);
    }
    appendMessage(payload.assistant_message);
    updateProgress(payload.progress);
    updateTerminal(payload.conversation_status, payload.outcome);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, options);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
  }

  async function ensureStarted() {
    if (app.dataset.status !== "in_progress") {
      updateTerminal(app.dataset.status, app.dataset.outcome);
      return;
    }
    networkBanner.hidden = true;
    setBusy(true);
    try {
      const payload = await request(`/api/conversations/${encodeURIComponent(conversationId)}/start`, { method: "POST" });
      applyResponse(payload);
    } catch (_error) {
      networkBanner.hidden = false;
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || app.dataset.status !== "in_progress") return;
    networkBanner.hidden = true;
    appendMessage({ role: "user", content: text, created_at: new Date().toISOString() });
    input.value = "";
    input.style.height = "auto";
    setBusy(true);
    try {
      const payload = await request(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      applyResponse(payload);
    } catch (_error) {
      networkBanner.hidden = false;
    } finally {
      setBusy(false);
      if (!input.disabled) input.focus();
    }
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  });
  retryButton.addEventListener("click", () => window.location.reload());
  const voiceDialog = document.querySelector("#voice-dialog");
  document.querySelector("#open-voice")?.addEventListener("click", () => voiceDialog.showModal());
  document.querySelector("#close-voice")?.addEventListener("click", () => voiceDialog.close());
  document.addEventListener("ui-language-change", () => {
    updateTerminal(app.dataset.status, app.dataset.outcome);
  });

  scrollToLatest();
  ensureStarted();
})();
