(() => {
  const root = document.documentElement;
  const candidateApp = document.querySelector("[data-ui-language]");
  const candidateDefault = candidateApp?.dataset.uiLanguage;
  const languageLocked = candidateApp?.dataset.languageLocked === "true";
  const saved = window.localStorage.getItem("grupo-sazon-ui-language");

  function applyLanguage(language) {
    const selected = language === "en" ? "en" : "es";
    root.lang = selected;
    document.querySelectorAll("[data-copy-es]").forEach((element) => {
      element.textContent = selected === "en" ? element.dataset.copyEn : element.dataset.copyEs;
    });
    document.querySelectorAll("[data-placeholder-es]").forEach((element) => {
      element.placeholder = selected === "en" ? element.dataset.placeholderEn : element.dataset.placeholderEs;
    });
    document.querySelectorAll("[data-aria-es]").forEach((element) => {
      element.setAttribute("aria-label", selected === "en" ? element.dataset.ariaEn : element.dataset.ariaEs);
    });
    document.querySelectorAll(".language-button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.language === selected));
    });
    if (!languageLocked) window.localStorage.setItem("grupo-sazon-ui-language", selected);
    document.dispatchEvent(new CustomEvent("ui-language-change", { detail: selected }));
  }

  document.querySelectorAll(".language-button").forEach((button) => {
    button.addEventListener("click", () => applyLanguage(button.dataset.language));
  });
  window.grupoSazonApplyLanguage = applyLanguage;
  applyLanguage(candidateDefault || saved || "es");
})();
