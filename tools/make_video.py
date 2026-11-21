"""Video dimostrativo di Smartbox dai test automatici e dal replay delle prove registrate.

Nessuna immagine del volto: solo le misure registrate fotogramma per fotogramma (indicatori.csv),
rielaborate con la logica attuale di smartbox/logic.py. I numeri mostrati sono calcolati qui, non scritti a mano.

Uso:  python make_video.py <repo edge> <cartella data delle prove> <file .mp4 di uscita>
"""
import copy, io, os, re, subprocess, sys

EDGE, DATA, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, EDGE)
sys.path.insert(0, os.path.join(EDGE, "tools"))

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml
from smartbox.logic import DrowsinessMonitor
from smartbox.config import check
from smartbox.calibration import blendshape_thresholds
from replay import load_indicators, merge
from evaluate import evaluate, load_annotations

W, H, FPS = 1280, 720, 30
DPI = 100
SPEED = 2.0                      # il replay di 60 s dura 30 s
BG, INK, MUTED = "#0f172a", "#f8fafc", "#94a3b8"
LEVEL_COL = {0: "#10b981", 1: "#f59e0b", 2: "#ef4444"}
LEVEL_TXT = {0: "NORMALE", 1: "ATTENZIONE", 2: "PERICOLO"}
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 13, "text.color": INK,
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED})

base = check(yaml.safe_load(open(os.path.join(EDGE, "config.yaml"), encoding="utf-8")), "config.yaml")
TOL = base["evaluation"]["tolerance_seconds"]


def fmt(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def cfg_for(folder, extra=None):
    cfg = copy.deepcopy(base)
    t = os.path.join(folder, "config_tarata.yaml")
    if os.path.exists(t):
        merge(cfg, yaml.safe_load(open(t, encoding="utf-8")))
    return merge(cfg, extra)


def run(folder, cfg):
    rows = load_indicators(os.path.join(folder, "indicatori.csv"))
    mon, events, levels = DrowsinessMonitor(cfg), [], []
    for t, ind in rows:
        ev = mon.update(ind, t)
        if ev:
            events.append(ev)
        levels.append(mon.level)
    ann = load_annotations(os.path.join(folder, "annotazioni_reali.csv"))
    det = [(e.t, e.reason) for e in events if e.level > e.prev_level]
    return rows, np.array(levels), events, ann, evaluate(det, ann, TOL)


def calib(folder):
    import csv
    o, c = [], []
    for r in csv.DictReader(open(os.path.join(folder, "indicatori.csv"), encoding="utf-8")):
        if str(r["face"]).lower() not in ("1", "true") or not r.get("blink"):
            continue
        t, p = float(r["t"]), (float(r["blink"]), float(r["squint"]))
        if 2.0 <= t <= 6.0:
            o.append(p)
        elif 23.0 <= t <= 24.5:
            c.append(p)
    return blendshape_thresholds(o, c, base["calibration"])


# ------------------------------------------------------------------ dati
P6 = os.path.join(DATA, "prova6")
std_cfg = cfg_for(P6)
cb = calib(P6)
cal_extra = {"indicators": {"eye_closure_source": "blendshape",
                            "blink_closed_threshold": cb["blink_closed_threshold"],
                            "blink_squint_margin": cb["blink_squint_margin"]}}
cal_cfg = cfg_for(P6, cal_extra)
STD = run(P6, std_cfg)
CAL = run(P6, cal_cfg)

summary = []
for n in (4, 5, 6, 7):
    f = os.path.join(DATA, f"prova{n}")
    b = calib(f)
    ex = {"indicators": {"eye_closure_source": "blendshape", "blink_closed_threshold": b["blink_closed_threshold"],
                         "blink_squint_margin": b["blink_squint_margin"]}}
    summary.append((n, run(f, cfg_for(f))[4], run(f, cfg_for(f, ex))[4]))

pt = subprocess.run([sys.executable, "-B", "-m", "pytest", "-v", "-p", "no:cacheprovider", "tests"],
                    cwd=EDGE, capture_output=True, text=True, encoding="utf-8")
tests = re.findall(r"::(test_\w+) PASSED", pt.stdout)
total = re.search(r"(\d+) passed", pt.stdout).group(1)
print(f"pytest: {total} superati; prova 6 tarata: {cb}")

# ------------------------------------------------------------------ disegno
writer = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"VP90"), FPS, (W, H))
assert writer.isOpened(), "codec VP90 non disponibile"


def emit(fig, n=1):
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
    frame = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    for _ in range(n):
        writer.write(frame)


def new_fig():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=BG)
    return fig


def fade_card(lines, seconds, footer=None):
    """lines: (testo, dimensione, colore, peso); comparsa graduale nei primi 0,6 s."""
    fig = new_fig()
    n = int(seconds * FPS)
    y0 = 0.5 + 0.055 * (len(lines) - 1)
    objs = []
    for i, (txt, size, col, weight) in enumerate(lines):
        objs.append(fig.text(0.5, y0 - i * 0.11, txt, ha="center", va="center", fontsize=size, color=col, weight=weight))
    if footer:
        objs.append(fig.text(0.5, 0.07, footer, ha="center", fontsize=12, color=MUTED))
    for k in range(n):
        a = min(1.0, k / (0.6 * FPS))
        for o in objs:
            o.set_alpha(a)
        emit(fig)
    plt.close(fig)


def scene_tests(seconds=9):
    fig = new_fig()
    ax = fig.add_axes([0.06, 0.08, 0.88, 0.8])
    ax.set_facecolor("#020617"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#334155")
    fig.text(0.06, 0.92, "1 · Test automatici della logica (pytest), prima di qualsiasi prova su Raspberry",
             fontsize=17, weight="bold")
    vis = 16
    texts = [ax.text(0.02, 0.95 - i * 0.056, "", transform=ax.transAxes, family="Consolas", fontsize=12.5, va="top")
             for i in range(vis + 2)]
    lines = [("$ python -m pytest -v tests", "#e2e8f0")] + \
            [(f"tests/test_logic.py::{t:<62} PASSED", "#4ade80") for t in tests]
    n = int(seconds * FPS)
    final_from = int(n * 0.82)
    for k in range(n):
        shown = min(len(lines), 1 + int(len(lines) * k / final_from))
        window = lines[max(0, shown - vis):shown]
        for i, tx in enumerate(texts):
            if i < len(window):
                tx.set_text(window[i][0]); tx.set_color(window[i][1])
            else:
                tx.set_text("")
        if k >= final_from:
            texts[len(window)].set_text(f"==================== {total} passed ====================")
            texts[len(window)].set_color("#4ade80"); texts[len(window)].set_weight("bold")
        emit(fig)
    plt.close(fig)


def scene_replay(data, cfg, title, subtitle):
    rows, levels, events, ann, res = data
    t = np.array([r[0] for r in rows])
    face = np.array([r[1].face_found for r in rows])
    blink = np.array([r[1].blink if r[1].face_found else np.nan for r in rows], float)
    marg = np.array([(r[1].blink - r[1].squint) if r[1].face_found else np.nan for r in rows], float)
    pitch = np.array([r[1].pitch if r[1].face_found else np.nan for r in rows], float)
    ic = cfg["indicators"]
    dur = t[-1]

    fig = new_fig()
    fig.text(0.04, 0.945, title, fontsize=19, weight="bold")
    fig.text(0.04, 0.905, subtitle, fontsize=12.5, color=MUTED)
    specs = [("Chiusura palpebra", blink, ic["blink_closed_threshold"], (0, 1)),
             ("Palpebra − occhi stretti", marg, ic["blink_squint_margin"], (-0.4, 1)),
             ("Inclinazione capo (°)", pitch, None, (np.nanmin(pitch) - 3, np.nanmax(pitch) + 3)),
             ("Livello", None, None, (-0.3, 2.4))]
    axes, curs, lines = [], [], []
    for i, (lab, y, thr, yl) in enumerate(specs):
        ax = fig.add_axes([0.05, 0.69 - i * 0.19, 0.62, 0.165])
        ax.set_facecolor("#111c33"); ax.set_xlim(0, dur); ax.set_ylim(*yl)
        for s in ax.spines.values():
            s.set_color("#334155")
        ax.text(0.006, 0.96, lab, transform=ax.transAxes, fontsize=11, color="#cbd5e1", va="top", zorder=5)
        if i < 3:
            ax.set_xticklabels([])
        else:
            ax.set_xlabel("tempo della prova (s)", fontsize=11)
            ax.set_yticks([0, 1, 2]); ax.set_yticklabels(["0", "1", "2"])
        for a0, a1, tipo in ann:
            ax.axvspan(a0, a1, color="#64748b", alpha=0.28, lw=0)
            if i == 0:
                ax.text((a0 + a1) / 2, yl[1] - 0.07 * (yl[1] - yl[0]), tipo.replace("_", " ").replace("chinamento", "capo chino"),
                        ha="center", va="top", fontsize=10.5, color="#cbd5e1")
        if thr is not None:
            ax.axhline(thr, color="#f472b6", lw=1.2, ls="--")
            ax.text(dur * 0.995, thr, f"soglia {fmt(thr)}", color="#f472b6", fontsize=10, ha="right", va="bottom")
        ln, = ax.plot([], [], color="#38bdf8" if i < 3 else "#e2e8f0", lw=1.4, drawstyle="steps-post" if i == 3 else None)
        lines.append(ln)
        curs.append(ax.axvline(0, color="#e2e8f0", lw=1, alpha=0.6))
        axes.append(ax)
    # riquadro di stato
    badge_ax = fig.add_axes([0.71, 0.56, 0.26, 0.3]); badge_ax.axis("off")
    badge = plt.Rectangle((0, 0), 1, 1, transform=badge_ax.transAxes, color=LEVEL_COL[0], ec="none")
    badge_ax.add_patch(badge)
    b_lvl = badge_ax.text(0.5, 0.62, "", ha="center", va="center", fontsize=30, weight="bold", color="#0f172a")
    b_why = badge_ax.text(0.5, 0.3, "", ha="center", va="center", fontsize=15, color="#0f172a")
    clock = fig.text(0.71, 0.875, "", fontsize=14, color=MUTED)
    log_title = fig.text(0.71, 0.5, "Eventi", fontsize=14, weight="bold")
    log = fig.text(0.71, 0.47, "", fontsize=12.5, va="top", family="Consolas", linespacing=1.5)
    outcome = fig.text(0.71, 0.2, "", fontsize=13, va="top", linespacing=1.6)

    level_fill = []
    n = int(dur / SPEED * FPS)
    hold = int(2.5 * FPS)
    for k in range(n + hold):
        now = min(dur, k * SPEED / FPS)
        j = int(np.searchsorted(t, now, side="right"))
        for i, (lab, y, thr, yl) in enumerate(specs):
            lines[i].set_data(t[:j], (levels if y is None else y)[:j])
            curs[i].set_xdata([now, now])
        lvl = int(levels[j - 1]) if j else 0
        badge.set_color(LEVEL_COL[lvl]); b_lvl.set_text(LEVEL_TXT[lvl])
        last = [e for e in events if e.t <= now]
        b_why.set_text(last[-1].reason if last and lvl > 0 else ("volto non rilevato" if j and not face[j - 1] else ""))
        clock.set_text(f"replay × {fmt(SPEED, 0)}   t = {fmt(now, 1)} s")
        log.set_text("\n".join(f"{fmt(e.t)} s  {e.prev_level}→{e.level}  {e.reason}" for e in last[-6:]))
        done = []
        for m in res["dettaglio"]:
            if now >= m["fine"] + TOL or now >= dur:
                tipo = m["tipo"].replace("_", " ").replace("chinamento", "capo chino")
                done.append(f"rilevato · {tipo}: allarme a {fmt(m['allarme_t'])} s" if m["allarme_t"] is not None
                            else f"MANCATO · {tipo}")
        outcome.set_text("\n".join(done))
        outcome.set_color("#e2e8f0")
        if k == n:
            outcome.set_text("\n".join(done) + f"\n\nprecisione {fmt(res['precisione'])} · richiamo {fmt(res['richiamo'])}")
        emit(fig)
    plt.close(fig)


def scene_calib(seconds=8):
    m = cb["misure"]
    fade_card([
        ("2 · Taratura sul guidatore (criterio P80)", 26, INK, "bold"),
        ("soglia = aperti + 0,8 × (chiusi − aperti), misurata con 5 s a occhi aperti e pochi secondi a occhi chiusi", 15, MUTED, "normal"),
        (f"palpebra:   aperti {fmt(m['palpebra_aperti'])}  →  chiusi {fmt(m['palpebra_chiusi'])}     soglia "
         f"{fmt(std_cfg['indicators']['blink_closed_threshold'])} → {fmt(cb['blink_closed_threshold'])}", 19, "#38bdf8", "normal"),
        (f"palpebra − occhi stretti:   aperti {fmt(m['scarto_aperti'])}  →  chiusi {fmt(m['scarto_chiusi'])}     margine "
         f"{fmt(std_cfg['indicators']['blink_squint_margin'])} → {fmt(cb['blink_squint_margin'])}", 19, "#38bdf8", "normal"),
        ("Con le soglie standard questo soggetto non supera il margine a occhi chiusi.", 16, "#fbbf24", "normal"),
    ], seconds, footer="Prova 6 · taratura sugli intervalli 2–6 s (aperti) e 23–24,5 s (chiusi) della stessa registrazione")


def scene_summary(seconds=10):
    fig = new_fig()
    fig.text(0.5, 0.86, "3 · Risultati sulle prove 4–7: precisione / richiamo", ha="center", fontsize=24, weight="bold")
    ax = fig.add_axes([0.14, 0.27, 0.72, 0.5]); ax.axis("off")
    cells = [[f"Prova {n}", f"{fmt(s['precisione'])} / {fmt(s['richiamo'])}", f"{fmt(c['precisione'])} / {fmt(c['richiamo'])}"]
             for n, s, c in summary]
    tb = ax.table(cellText=cells, colLabels=["", "soglie standard", "soglie tarate"],
                  loc="center", cellLoc="center")
    tb.auto_set_font_size(False); tb.set_fontsize(17); tb.scale(1, 2.6)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor("#334155")
        cell.set_facecolor("#1e293b" if r == 0 else "#111c33")
        cell.get_text().set_color(INK if r == 0 or c == 0 else ("#4ade80" if "1,00 / 1,00" in cell.get_text().get_text() else "#fbbf24"))
    fig.text(0.5, 0.15, "Verifica ottimistica: taratura e valutazione sulla stessa registrazione. "
                        "Serve a confrontare soglie fisse e tarate,", ha="center", fontsize=13, color=MUTED)
    fig.text(0.5, 0.11, "non a misurare le prestazioni: la validazione su più soggetti resta da fare.",
             ha="center", fontsize=13, color=MUTED)
    emit(fig, int(seconds * FPS))
    plt.close(fig)


fade_card([("Smartbox", 54, INK, "bold"),
           ("Monitoraggio della sonnolenza del guidatore", 24, "#bfdbfe", "normal"),
           ("Test automatici e replay delle prove registrate", 18, MUTED, "normal")], 4.5,
          footer="Nessuna immagine del volto: solo le misure registrate, rielaborate con la logica attuale del dispositivo")
scene_tests()
scene_replay(STD, std_cfg, "Prova 6 · soglie standard",
             f"Occhio chiuso: palpebra ≥ {fmt(std_cfg['indicators']['blink_closed_threshold'])} "
             f"e scarto ≥ {fmt(std_cfg['indicators']['blink_squint_margin'])} per "
             f"{fmt(base['alarm']['microsleep_seconds'], 1)} s · grigio: episodi reali")
scene_calib()
scene_replay(CAL, cal_cfg, "Prova 6 · soglie tarate sul guidatore",
             f"Occhio chiuso: palpebra ≥ {fmt(cb['blink_closed_threshold'])} "
             f"e scarto ≥ {fmt(cb['blink_squint_margin'])} · stessi dati, stessa logica")
scene_summary()
fade_card([("Smartbox", 40, INK, "bold"),
           ("Raspberry Pi 5 nel veicolo  →  backend MQTT/HTTP  →  dashboard di flotta", 19, "#bfdbfe", "normal"),
           ("Prossimo passo: prove su Raspberry e su più soggetti", 17, MUTED, "normal")], 5,
          footer="Corso di perfezionamento 2025/26 · UniSalento IDA Lab")
writer.release()
print("scritto", OUT, f"{os.path.getsize(OUT) / 1e6:.1f} MB")
