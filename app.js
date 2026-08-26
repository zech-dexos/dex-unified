const API = "https://dex-backend-production-2bbe.up.railway.app/analyze";

function tryExample(el) {
  document.getElementById("inputField").value = el.textContent;
  send();
}

document.getElementById("inputField").addEventListener("keydown", e => {
  if (e.key === "Enter") send();
});

async function send() {
  const input = document.getElementById("inputField").value.trim();
  if (!input) return;

  const btn = document.getElementById("sendBtn");
  const result = document.getElementById("result");

  btn.disabled = true;
  btn.textContent = "THINKING...";
  result.style.display = "none";

  try {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    render(data);

  } catch (err) {
    result.style.display = "block";
    result.innerHTML = `<div class="error-box">⚠ Could not reach ReasonFlow API: ${err.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "ANALYZE →";
  }
}

function render(d) {
  const result = document.getElementById("result");
  result.style.display = "block";

  // Sort branches descending
  const branches = [...d.branches].sort((a, b) => b.weight - a.weight);
  const maxW = branches[0]?.weight || 1;

  // Modifiers
  const mods = (d.modifiers || []).length
    ? d.modifiers.map(m => `<span class="tag tag-mod">${m}</span>`).join("")
    : `<span class="tag tag-none">none</span>`;

  // Tools
  const tools = (d.tools || []).length
    ? d.tools.map(t => `<span class="tag tag-tool">${t}</span>`).join("")
    : `<span class="tag tag-none">none</span>`;

  // Branch bars
  const barsHTML = branches.map((b, i) => {
    const isWinner = i === 0;
    const pct = Math.round((b.weight / maxW) * 100);
    return `
      <div class="branch-row" style="animation-delay:${i * 0.05}s">
        <span class="branch-name ${isWinner ? "winner" : ""}">${isWinner ? "▶ " : ""}${b.id}</span>
        <div class="bar-track">
          <div class="bar-fill ${isWinner ? "winner" : ""}" data-pct="${pct}"></div>
        </div>
        <span class="branch-weight">${b.weight.toFixed(2)}</span>
      </div>`;
  }).join("");

  result.innerHTML = `
    <div class="panel-header">
      <span><span class="status-dot"></span>SIGNAL RESOLVED</span>
      <span style="color:var(--text-dim);font-size:11px">${new Date().toLocaleTimeString()}</span>
    </div>

    <div class="signal-grid">
      <div class="sig-card" style="animation-delay:0s">
        <div class="sig-label">Intent</div>
        <div class="sig-value accent">${d.intent}</div>
      </div>
      <div class="sig-card" style="animation-delay:0.05s">
        <div class="sig-label">Domain</div>
        <div class="sig-value accent2">${d.domain}</div>
      </div>
      <div class="sig-card" style="animation-delay:0.1s">
        <div class="sig-label">Modifiers</div>
        <div class="tag-row">${mods}</div>
      </div>
      <div class="sig-card" style="animation-delay:0.15s">
        <div class="sig-label">Tools</div>
        <div class="tag-row">${tools}</div>
      </div>
      <div class="sig-card full" style="animation-delay:0.2s">
        <div class="sig-label">Reasoning Branches</div>
        <div class="branch-list" style="margin-top:10px">${barsHTML}</div>
      </div>
    </div>

    <div class="ctx-block" style="animation-delay:0.3s">
      ${d.context}
    </div>
  `;

  // Animate bars after render
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      document.querySelectorAll(".bar-fill").forEach(bar => {
        bar.style.width = bar.dataset.pct + "%";
      });
    });
  });
}
