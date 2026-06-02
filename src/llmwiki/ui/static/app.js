async function loadStatus() {
  const response = await fetch("/api/status");
  const status = await response.json();
  const line = document.querySelector("#status-line");
  if (line) {
    line.textContent = `Workspace status: ${status.status}`;
  }
}

loadStatus().catch((error) => {
  const line = document.querySelector("#status-line");
  if (line) {
    line.textContent = `Unable to load dashboard: ${error.message}`;
  }
});
