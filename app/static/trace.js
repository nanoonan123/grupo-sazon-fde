(() => {
  const status = document.querySelector("#trace-poll-status");
  if (!status) return;

  let latestSignature;
  const poll = async () => {
    try {
      const response = await fetch(status.dataset.traceEndpoint, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      const signature = JSON.stringify(payload.latest_turn);
      if (latestSignature === undefined) {
        latestSignature = signature;
      } else if (signature !== latestSignature) {
        window.location.reload();
      }
    } catch {
      // The manual refresh remains available if lightweight polling is interrupted.
    }
  };

  void poll();
  window.setInterval(poll, 2000);
})();
