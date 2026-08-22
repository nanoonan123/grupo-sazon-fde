(() => {
  const copyButton = document.querySelector("#copy-link");
  const urlField = document.querySelector("#candidate-url");
  if (!copyButton || !urlField) return;
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(urlField.value);
      copyButton.textContent = document.documentElement.lang === "en" ? "Copied" : "Copiado";
    } catch (_error) {
      urlField.select();
      document.execCommand("copy");
    }
  });
})();
