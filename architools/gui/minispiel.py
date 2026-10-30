"""Minispiel für lange Wartezeiten: „Abgabe-Lauf“ mit Zirkel Zacharias und Rosi Radiergummi.

Läuft komplett im Browser (Zeichenfläche + JavaScript), belastet das Programm nicht und rechnet auch während eines Exports weiter.
Leertaste / Pfeil hoch / Antippen = springen, 1 = Zacharias, 2 = Rosi, P = Pause. Der Rekord merkt sich der Browser (localStorage).
"""
from nicegui import ui

from .stil import url

JS = r"""
(function(){
  if (window.__zzSpiel) { window.__zzSpiel.stop(); }
  const cv = document.getElementById('__ID__'); if (!cv) return;
  const ctx = cv.getContext('2d'); const W = cv.width = 760, H = cv.height = 300, G = 242;
  const bild = {z: new Image(), r: new Image()}; bild.z.src = '__ZAC__'; bild.r.src = '__ROSI__';
  const FIG = {z: {name: 'Zirkel Zacharias', h: 62, v: 660, g: 2000, farbe: '#c9a227'},
               r: {name: 'Rosi Radiergummi', h: 56, v: 560, g: 1300, farbe: '#e58aa0'}};
  let best = 0; try { best = +localStorage.getItem('zzBest') || 0; } catch (e) {}
  let st, lauf = true, last = 0, spur = [];
  function neu(held) {
    st = {held: held || (st && st.held) || 'z', t: 0, speed: 270, dist: 0, punkte: 0, stifte: 0, zustand: 'start', pause: false,
          y: 0, vy: 0, am_boden: true, hindernisse: [], stifte_liste: [], naechstes: 1.1, naechster_stift: 0.7, grund: ''};
    spur = [];
  }
  neu('z');
  function springen() {
    if (st.zustand === 'start') { st.zustand = 'lauf'; }
    else if (st.zustand === 'ende') { if (st.t_ende > 0.5) neu(); return; }
    if (st.pause) { st.pause = false; return; }
    if (st.am_boden) { st.vy = -FIG[st.held].v; st.am_boden = false; }
  }
  function taste(e) {
    if (!document.getElementById('__ID__')) { stop(); return; }
    const k = e.key;
    if (k === ' ' || k === 'ArrowUp' || k === 'w' || k === 'W') { e.preventDefault(); springen(); }
    else if (k === '1' && st.zustand !== 'lauf') { st.held = 'z'; }
    else if (k === '2' && st.zustand !== 'lauf') { st.held = 'r'; }
    else if (k === 'p' || k === 'P') { if (st.zustand === 'lauf') st.pause = !st.pause; }
  }
  function zeiger(e) {
    const r = cv.getBoundingClientRect(); const x = (e.clientX - r.left) / r.width * W, y = (e.clientY - r.top) / r.height * H;
    if (st.zustand === 'start' && y > 150 && y < 250) { if (x > 180 && x < 380) { st.held = 'z'; return; } if (x > 380 && x < 580) { st.held = 'r'; return; } }
    springen();
  }
  document.addEventListener('keydown', taste, true); cv.addEventListener('pointerdown', zeiger);
  function stop() { lauf = false; document.removeEventListener('keydown', taste, true); cv.removeEventListener('pointerdown', zeiger); }
  window.__zzSpiel = {stop: stop, zustand: () => st};

  function rnd(a, b) { return a + Math.random() * (b - a); }
  function schritt(dt) {
    if (st.zustand !== 'lauf' || st.pause) { if (st.zustand === 'ende') st.t_ende += dt; return; }
    const f = FIG[st.held];
    st.t += dt; st.speed = 270 + Math.min(st.t * 7, 330); st.dist += st.speed * dt; st.punkte = Math.floor(st.dist / 10) + st.stifte * 10;
    st.vy += f.g * dt; st.y += st.vy * dt; if (st.y >= 0) { st.y = 0; st.vy = 0; st.am_boden = true; }
    spur.push(st.y); if (spur.length > 40) spur.shift();
    st.naechstes -= dt;
    if (st.naechstes <= 0) {
      const art = ['klecks', 'tasse', 'stapel'][Math.floor(Math.random() * 3)];
      const d = {klecks: [38, 24], tasse: [30, 40], stapel: [44, 56]}[art];
      st.hindernisse.push({art: art, x: W + 20, w: d[0], h: d[1]});
      st.naechstes = rnd(1.0, 1.9) * Math.max(0.62, 1 - st.t / 140) + 0.25;
    }
    st.naechster_stift -= dt;
    if (st.naechster_stift <= 0) { st.stifte_liste.push({x: W + 20, y: rnd(60, 120), geholt: false}); st.naechster_stift = rnd(1.2, 2.6); }
    for (const o of st.hindernisse) o.x -= st.speed * dt;
    for (const s of st.stifte_liste) s.x -= st.speed * dt;
    st.hindernisse = st.hindernisse.filter(o => o.x > -80); st.stifte_liste = st.stifte_liste.filter(s => s.x > -40 && !s.geholt);
    const hx = 150, hb = 26, hh = f.h - 10, hy = G + st.y;                 // Trefferfläche der Figur (etwas kleiner als das Bild)
    for (const o of st.hindernisse) {
      if (hx + hb / 2 - 4 > o.x + 4 && hx - hb / 2 + 4 < o.x + o.w - 4 && hy > G - o.h + 6) {
        st.zustand = 'ende'; st.t_ende = 0; st.grund = {klecks: 'Tintenklecks!', tasse: 'Kaffee über den Plan!', stapel: 'Der Papierstapel war schneller.'}[o.art];
        if (st.punkte > best) { best = st.punkte; try { localStorage.setItem('zzBest', best); } catch (e) {} }
      }
    }
    for (const s of st.stifte_liste) {
      if (!s.geholt && Math.abs(s.x + 14 - hx) < 26 && Math.abs((G - s.y) - (hy - hh / 2)) < 38) { s.geholt = true; st.stifte++; }
    }
  }
  function figur(k, x, y, h) {
    const b = bild[k]; if (b.complete && b.naturalWidth) { const w = h * b.naturalWidth / b.naturalHeight; ctx.drawImage(b, x - w / 2, y - h, w, h); }
    else { ctx.fillStyle = FIG[k].farbe; ctx.fillRect(x - 14, y - h, 28, h); }
  }
  function zeichne() {
    ctx.fillStyle = '#f4efe3'; ctx.fillRect(0, 0, W, H);
    const off = st.zustand === 'lauf' && !st.pause ? st.dist : st.dist;
    ctx.strokeStyle = '#e4dcc8'; ctx.lineWidth = 1;                      // Rasterpapier, läuft mit
    for (let x = -((off * 0.5) % 40); x < W; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, G); ctx.stroke(); }
    for (let y = 22; y < G; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    ctx.fillStyle = '#e9e1cd';                                           // ferne Gebäude (Parallax)
    for (let i = 0; i < 12; i++) { const bx = ((i * 140 - off * 0.2) % (W + 140) + W + 140) % (W + 140) - 70; const bh = 40 + (i * 37 % 60); ctx.fillRect(bx, G - bh, 90, bh); }
    ctx.strokeStyle = '#4a4f55'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(0, G + 2); ctx.lineTo(W, G + 2); ctx.stroke();
    ctx.lineWidth = 1; ctx.strokeStyle = '#9aa0a6';
    for (let x = -((off) % 30); x < W; x += 30) { ctx.beginPath(); ctx.moveTo(x, G + 8); ctx.lineTo(x + 12, G + 8); ctx.stroke(); }
    for (const s of st.stifte_liste) {                                  // Bleistifte
      const y = G - s.y; ctx.save(); ctx.translate(s.x, y); ctx.rotate(-0.35);
      ctx.fillStyle = '#e2b53a'; ctx.fillRect(0, -4, 24, 8); ctx.fillStyle = '#e58aa0'; ctx.fillRect(-5, -4, 5, 8);
      ctx.fillStyle = '#f0d9b0'; ctx.beginPath(); ctx.moveTo(24, -4); ctx.lineTo(32, 0); ctx.lineTo(24, 4); ctx.fill();
      ctx.fillStyle = '#333'; ctx.beginPath(); ctx.moveTo(29, -1.2); ctx.lineTo(32, 0); ctx.lineTo(29, 1.2); ctx.fill(); ctx.restore();
    }
    for (const o of st.hindernisse) {
      const x = o.x, y = G - o.h;
      if (o.art === 'klecks') {
        ctx.fillStyle = '#1f3b73'; ctx.beginPath(); ctx.ellipse(x + o.w / 2, G - 9, o.w / 2, 11, 0, Math.PI, 0); ctx.fill();
        ctx.fillRect(x, G - 9, o.w, 9); ctx.beginPath(); ctx.arc(x + 6, G - 15, 5, 0, 7); ctx.arc(x + o.w - 8, G - 20, 4, 0, 7); ctx.fill();
      } else if (o.art === 'tasse') {
        ctx.fillStyle = '#fbfaf6'; ctx.strokeStyle = '#555'; ctx.lineWidth = 2; ctx.fillRect(x, y + 6, o.w - 6, o.h - 6); ctx.strokeRect(x, y + 6, o.w - 6, o.h - 6);
        ctx.beginPath(); ctx.arc(x + o.w - 6, y + 22, 8, -1.3, 1.3); ctx.stroke(); ctx.fillStyle = '#6b4226'; ctx.fillRect(x + 2, y + 8, o.w - 10, 6);
        ctx.strokeStyle = '#b8b2a2'; ctx.beginPath(); ctx.moveTo(x + 8, y); ctx.quadraticCurveTo(x + 2, y - 5, x + 9, y + 4); ctx.stroke();
      } else {
        for (let i = 0; i < 6; i++) { ctx.fillStyle = i % 2 ? '#ffffff' : '#f7f4ec'; ctx.strokeStyle = '#8b8b8b'; ctx.lineWidth = 1;
          const yy = G - (i + 1) * o.h / 6; ctx.fillRect(x + (i % 3) * 2, yy, o.w - 4, o.h / 6); ctx.strokeRect(x + (i % 3) * 2, yy, o.w - 4, o.h / 6); }
      }
    }
    const f = FIG[st.held], zweit = st.held === 'z' ? 'r' : 'z';
    const yz = spur.length > 14 ? spur[spur.length - 14] : 0;            // der/die andere folgt mit kleiner Verzögerung
    if (st.zustand !== 'start') figur(zweit, 82, G + yz + 2, FIG[zweit].h);
    figur(st.held, 150, G + st.y + 2, f.h);
    ctx.fillStyle = '#1d2329'; ctx.font = '600 15px system-ui, sans-serif'; ctx.textAlign = 'right';
    ctx.fillText('Punkte ' + st.punkte + '   Rekord ' + Math.max(best, st.punkte) + '   Stifte ' + st.stifte, W - 14, 24);
    ctx.textAlign = 'center';
    if (st.zustand === 'start') {
      ctx.fillStyle = 'rgba(244,239,227,.88)'; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#1d2329'; ctx.font = 'italic 28px Georgia, serif'; ctx.fillText('Abgabe-Lauf', W / 2, 52);
      ctx.font = '14px system-ui, sans-serif'; ctx.fillText('Die Abgabe naht! Spring über Klekse, Kaffee und Papierstapel, sammle Bleistifte.', W / 2, 82);
      ctx.fillText('Leertaste, Pfeil hoch oder Antippen = springen   ·   P = Pause', W / 2, 106);
      for (const [k, cx, t, t2] of [['z', 280, '1 · Zirkel Zacharias', 'springt hoch'], ['r', 480, '2 · Rosi Radiergummi', 'schwebt länger']]) {
        ctx.fillStyle = st.held === k ? '#dfe9e8' : 'rgba(0,0,0,.04)'; ctx.fillRect(cx - 100, 140, 200, 118);
        ctx.strokeStyle = st.held === k ? '#1f6f78' : '#c9c2b0'; ctx.lineWidth = 2; ctx.strokeRect(cx - 100, 140, 200, 118);
        figur(k, cx, 208, FIG[k].h); ctx.fillStyle = '#1d2329'; ctx.font = '600 12px system-ui, sans-serif'; ctx.fillText(t, cx, 234); ctx.font = '11px system-ui, sans-serif'; ctx.fillText(t2, cx, 250);
      }
      ctx.font = '600 14px system-ui, sans-serif'; ctx.fillText('Los geht’s mit Leertaste', W / 2, 284);
    } else if (st.zustand === 'ende') {
      ctx.fillStyle = 'rgba(244,239,227,.8)'; ctx.fillRect(0, 70, W, 130);
      ctx.fillStyle = '#b4472b'; ctx.font = 'italic 26px Georgia, serif'; ctx.fillText(st.grund, W / 2, 112);
      ctx.fillStyle = '#1d2329'; ctx.font = '15px system-ui, sans-serif';
      ctx.fillText(st.punkte + ' Punkte' + (st.punkte >= best && st.punkte > 0 ? ' – neuer Rekord!' : '') + '   ·   noch einmal: Leertaste', W / 2, 146);
      ctx.fillText('(1 / 2 wechselt die Figur)', W / 2, 172);
    } else if (st.pause) {
      ctx.fillStyle = 'rgba(244,239,227,.7)'; ctx.fillRect(0, 100, W, 80); ctx.fillStyle = '#1d2329'; ctx.font = '22px Georgia, serif'; ctx.fillText('Pause – Leertaste oder P', W / 2, 148);
    }
  }
  function lauf_(ts) {
    if (!lauf) return;
    if (!document.getElementById('__ID__')) { stop(); return; }
    const dt = Math.min(0.05, (ts - last) / 1000 || 0); last = ts; schritt(dt); zeichne(); requestAnimationFrame(lauf_);
  }
  requestAnimationFrame(lauf_);
})();
"""


def oeffnen():
    """Öffnet das Minispiel in einem Fenster."""
    from . import figuren
    try:
        zac, rosi = url(figuren.sprite("3d")), url(figuren.sprite("rosi"))
    except Exception as e:
        ui.notify(f"Minispiel nicht möglich: {e}", type="warning")
        return
    with ui.dialog() as d, ui.card().classes("p-3").style("width:820px; max-width:96vw"):
        with ui.row().classes("w-full items-center"):
            ui.label("Minispiel – Abgabe-Lauf").classes("text-subtitle1")
            ui.label("läuft im Browser, der Export rechnet weiter").classes("text-caption").style("color:#7a8691")
            ui.space()
            ui.button(icon="close", on_click=d.close).props("flat round dense")
        cv = ui.element("canvas").style("width:100%; border:1px solid #c9c2b0; border-radius:6px; background:#f4efe3; touch-action:manipulation")
    d.on("hide", lambda: ui.run_javascript("window.__zzSpiel && window.__zzSpiel.stop()"))
    d.open()
    js = JS.replace("__ID__", f"c{cv.id}").replace("__ZAC__", zac).replace("__ROSI__", rosi)
    ui.timer(0.4, lambda: ui.run_javascript(js), once=True)
