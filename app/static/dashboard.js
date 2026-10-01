(() => {
  const { eventId, units, simulate } = window.RANGKON;
  let data = null;
  let unit = "";

  const WA = { pending: "Menunggu", sent: "Dihantar", delivered: "Sampai", read: "Dibaca", failed: "Gagal" };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const pct = (n, d) => (d ? Math.round((n / d) * 100) : 0);

  function stat(cls, n, label, sub) {
    return `<div class="stat ${cls}"><div class="n">${n}</div><div class="l">${label}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }

  function renderOverall(s, title) {
    document.getElementById("overall").innerHTML =
      stat("", s.total, `Dipanggil${title ? " - " + esc(title) : ""}`) +
      stat("accepted", s.accepted, "Diterima (TERIMA)", `${pct(s.accepted, s.total)}%`) +
      stat("pending", s.no_response, "Belum terima") +
      stat("declined", s.declined, "Tolak") +
      stat("attended", s.attended, "Hadir", `${pct(s.attended, s.total)}%`) +
      stat("sent", s.read, "WhatsApp dibaca", `${s.delivered} sampai / ${s.failed} gagal`);
  }

  function renderUnits() {
    const el = document.getElementById("units");
    el.innerHTML = Object.entries(data.units)
      .map(([name, s]) => `
        <div class="unit-card ${unit === name ? "active" : ""}" data-unit="${esc(name)}">
          <h3><span>${esc(name)}</span><span class="muted">${s.total} orang</span></h3>
          <div class="bar" title="Penerimaan"><i class="a" style="width:${pct(s.accepted, s.total)}%"></i><i class="d" style="width:${pct(s.declined, s.total)}%"></i></div>
          <div class="kv">
            <span class="c-accepted">Diterima</span><b>${s.accepted} (${pct(s.accepted, s.total)}%)</b>
            <span>Belum terima</span><b>${s.no_response}</b>
            <span>Tolak</span><b>${s.declined}</b>
          </div>
          <div class="bar" title="Kehadiran"><i class="h" style="width:${pct(s.attended, s.total)}%"></i></div>
          <div class="kv">
            <span class="c-attended">Hadir</span><b>${s.attended} (${pct(s.attended, s.total)}%)</b>
            <span>WhatsApp dibaca / gagal</span><b>${s.read} / ${s.failed}</b>
          </div>
        </div>`)
      .join("");
    el.querySelectorAll(".unit-card").forEach((c) => c.addEventListener("click", () => setUnit(c.dataset.unit === unit ? "" : c.dataset.unit)));
  }

  function matches(r, f, q) {
    if (unit && r.unit !== unit) return false;
    if (q && !(r.name.toLowerCase().includes(q) || r.phone.includes(q))) return false;
    switch (f) {
      case "no_response": return !r.rsvp;
      case "accepted": return r.rsvp === "accepted";
      case "declined": return r.rsvp === "declined";
      case "attended": return !!r.attended_at;
      case "not_attended": return !r.attended_at;
      case "failed": return r.status === "failed";
      default: return true;
    }
  }

  function rsvpCell(r) {
    if (r.rsvp === "accepted") return `<span class="badge b-accepted">TERIMA</span><div class="sub">${esc(r.rsvp_at)} (${esc(r.rsvp_via)})</div>`;
    if (r.rsvp === "declined") return `<span class="badge b-declined">TOLAK</span><div class="sub">${esc(r.rsvp_at)} (${esc(r.rsvp_via)})</div>`;
    return `<span class="badge b-none">BELUM TERIMA</span>${r.reply ? `<div class="sub">Balasan: "${esc(r.reply)}"</div>` : ""}`;
  }

  function waCell(r) {
    const cls = r.status === "failed" ? "b-failed" : "b-wa";
    const when = r.read_at || r.delivered_at || r.sent_at;
    return `<span class="badge ${cls}">${WA[r.status] || r.status}</span><div class="sub">${esc(r.status === "failed" ? r.error : when)}</div>`;
  }

  function actions(r) {
    let html = `<button class="sim" data-act="attend" data-id="${r.id}">${r.attended_at ? "Batal hadir" : "Tanda hadir"}</button> `;
    html += r.rsvp === "accepted"
      ? `<button class="sim" data-act="rsvp" data-v="clear" data-id="${r.id}">Batal terima</button>`
      : `<button class="sim" data-act="rsvp" data-v="accepted" data-id="${r.id}">Tanda terima</button>`;
    if (simulate && r.status !== "pending" && r.status !== "failed") {
      html += `<div class="sub">Simulasi: ${["delivered", "read", "TERIMA", "TOLAK"].map((a) => `<button class="sim" data-act="sim" data-v="${a}" data-id="${r.id}">${a}</button>`).join(" ")}</div>`;
    }
    return html;
  }

  function renderRows() {
    const f = document.getElementById("filter").value;
    const q = document.getElementById("search").value.trim().toLowerCase();
    const rows = data.rows.filter((r) => matches(r, f, q));
    document.getElementById("rows").innerHTML = rows.length
      ? rows.map((r) => `<tr>
          <td><span class="pill">${esc(r.unit)}</span></td>
          <td>${esc(r.rank)} ${esc(r.name)}</td>
          <td>+${esc(r.phone)}</td>
          <td>${waCell(r)}</td>
          <td>${rsvpCell(r)}</td>
          <td>${r.attended_at ? `<span class="badge b-attended">HADIR</span><div class="sub">${esc(r.attended_at)} (${esc(r.checkin_method)})</div>` : "-"}</td>
          <td>${actions(r)}</td></tr>`).join("")
      : `<tr><td colspan="7" class="empty">${data.rows.length ? "Tiada rekod sepadan" : "Belum ada panggilan dihantar. Tekan <b>Hantar WhatsApp</b>."}</td></tr>`;
  }

  function render() {
    renderOverall(unit ? data.units[unit] : data.overall, unit);
    renderUnits();
    renderRows();
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.unit === unit));
  }

  function setUnit(u) { unit = u; render(); }

  async function load() {
    const r = await fetch(`/api/events/${eventId}/dashboard`);
    if (r.status === 401) { location.href = "/login"; return; }
    data = await r.json();
    render();
  }

  async function post(url, body) {
    await fetch(url, { method: "POST", body: new URLSearchParams(body) });
    await load();
  }

  document.getElementById("tabs").addEventListener("click", (e) => { if (e.target.dataset.unit !== undefined) setUnit(e.target.dataset.unit); });
  document.getElementById("filter").addEventListener("change", renderRows);
  document.getElementById("search").addEventListener("input", renderRows);
  document.getElementById("rows").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const id = b.dataset.id;
    if (b.dataset.act === "attend") post(`/api/invitations/${id}/attend`, {});
    if (b.dataset.act === "rsvp") post(`/api/invitations/${id}/rsvp`, { answer: b.dataset.v });
    if (b.dataset.act === "sim") post(`/api/invitations/${id}/simulate`, { action: b.dataset.v });
  });

  void units;
  load();
  setInterval(load, 5000);
})();
