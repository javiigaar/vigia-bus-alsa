"""Vigila los buses ALSA Burgos -> Valladolid y avisa por Telegram cuando se liberan plazas.

Lee las fechas de config.json, guarda estado e historial en data/state.json.
Estados de cada servicio: "V" (a la venta), "F" (completo), "absent" (no aparece).
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"
STATE = ROOT / "data" / "state.json"
TZ = ZoneInfo("Europe/Madrid")

BASE = "https://www.alsa.es"
PORTLET = "com_babel_alsa_espania_purchase_web_PurchasePortlet"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

STATE_LABEL = {"V": "a la venta", "F": "completo", "absent": "no aparece"}
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Alsa:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
        self.token = None

    def login(self):
        r = self.s.get(BASE + "/", timeout=30)
        r.raise_for_status()
        m = (re.search(r"authToken\s*=\s*['\"]([^'\"]+)", r.text)
             or re.search(r"p_auth=([A-Za-z0-9]+)", r.text))
        if not m:
            raise RuntimeError("No encuentro el token p_auth en la portada de ALSA")
        self.token = m.group(1)

    def journeys(self, origin, destination, day: date):
        """Devuelve la lista de viajes de ALSA para ese día (incluye los completos con canBeSold='F')."""
        if not self.token:
            self.login()
        q = {
            "p_p_id": PORTLET, "p_p_lifecycle": "1", "p_p_state": "normal", "p_p_mode": "view",
            f"_{PORTLET}_javax.portlet.action": "SearchJourneysAction",
            "p_auth": self.token, "alsaspam": "",
            "originStationId": origin, "destinationStationId": destination,
            "departureDate": day.strftime("%d/%m/%Y"), "returnDate": "", "seats": "1",
            "promoCode": "", "youngPromoCode": "", "travelType": "OUTWARD",
            "employee": "false", "passengerType-4": "1",
        }
        self.s.get(BASE + "/checkout", params=q, timeout=30).raise_for_status()
        r = self.s.get(BASE + "/checkout", params={
            "p_p_id": PORTLET, "p_p_lifecycle": "2", "p_p_state": "normal", "p_p_mode": "view",
            "p_p_resource_id": "GetJourneyListResource",
            "p_p_cacheability": "cacheLevelPage", "journeyDirection": "I",
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Si la búsqueda no quedó en sesión, ALSA devuelve los viajes de otro día: lo comprobamos
        want = day.strftime("%d/%m/%Y")
        out = []
        for j in data.get("journeys", []):
            if j.get("departureStrGeneral") != want:
                raise RuntimeError(f"ALSA devolvió {j.get('departureStrGeneral')} en vez de {want}")
            out.append({
                "svc": str(j.get("serviceCodes")),
                "time": j.get("departureTime"),
                "arrival": j.get("arrivalTime"),
                "state": "V" if j.get("canBeSold") == "V" else "F",
                "price": (j.get("fares") or [{}])[0].get("price"),
            })
        return out


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram desactivado]", text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20).raise_for_status()
    except requests.RequestException as e:
        print("Error enviando Telegram:", e)


def in_window(t, window):
    return window[0] <= t <= window[1]


def fmt_day(d: date):
    return f"{WEEKDAYS[d.weekday()]} {d.day}/{d.month}"


def check_once(alsa, config, state):
    """Hace una ronda de comprobaciones. Devuelve True si el estado ha cambiado."""
    today = datetime.now(TZ).date()
    window = config.get("window", ["17:45", "18:45"])
    changed = False
    dates_state = state.setdefault("dates", {})

    for iso in sorted(config.get("dates", [])):
        day = date.fromisoformat(iso)
        if day < today:
            continue
        try:
            journeys = alsa.journeys(config["origin"], config["destination"], day)
        except Exception as e:  # noqa: BLE001 - un fallo en una fecha no debe parar el resto
            print(f"{iso}: error {e}")
            alsa.token = None
            continue

        ds = dates_state.setdefault(iso, {"services": {}, "events": []})
        ds["lastCheck"] = now_iso()
        seen = {j["svc"]: j for j in journeys}
        ts = now_iso()

        # Servicios que siguen/vuelven a aparecer
        for svc, j in seen.items():
            prev = ds["services"].get(svc)
            prev_state = prev["state"] if prev else "absent"
            ds["services"][svc] = {
                "time": j["time"], "arrival": j["arrival"], "state": j["state"],
                "price": j["price"],
                "since": prev["since"] if prev and prev_state == j["state"] else ts,
                "firstSeen": prev.get("firstSeen", ts) if prev else ts,
            }
            if prev_state != j["state"]:
                changed = True
                watched = in_window(j["time"], window)
                is_first_check = not ds.get("initialized")
                if watched and not is_first_check:
                    ds["events"].append({"at": ts, "svc": svc, "time": j["time"],
                                         "from": prev_state, "to": j["state"]})
                if watched and j["state"] == "V" and not is_first_check:
                    nuevo = " (¡bus nuevo / refuerzo!)" if prev is None else ""
                    telegram(
                        f"🟢 <b>¡Plaza libre!</b>{nuevo}\n"
                        f"Burgos → Valladolid <b>{j['time']}</b> ({fmt_day(day)})\n"
                        f"Llegada {j['arrival']}\n\n👉 https://www.alsa.es"
                    )
                elif watched and prev_state == "V" and not is_first_check:
                    telegram(f"🔴 Se ha vuelto a llenar el de las {j['time']} del {fmt_day(day)}.")
            print(f"{iso} {j['time']} [{svc}] {j['state']}")

        # Servicios que han desaparecido de la lista
        for svc, prev in ds["services"].items():
            if svc not in seen and prev["state"] != "absent":
                changed = True
                if in_window(prev["time"], window):
                    ds["events"].append({"at": ts, "svc": svc, "time": prev["time"],
                                         "from": prev["state"], "to": "absent"})
                    if prev["state"] == "V" and ds.get("initialized"):
                        telegram(f"🔴 El de las {prev['time']} del {fmt_day(day)} ya no aparece.")
                prev["state"] = "absent"
                prev["since"] = ts

        if not ds.get("initialized"):
            ds["initialized"] = True
            ds["firstCheck"] = ts
            changed = True
            win = [j for j in journeys if in_window(j["time"], window)]
            libres = [j for j in win if j["state"] == "V"]
            if libres:
                telegram("🟢 Empiezo a vigilar el " + fmt_day(day) + " y ya hay plaza en: "
                         + ", ".join(j["time"] for j in libres) + "\n👉 https://www.alsa.es")
        time.sleep(1.5)  # no saturar a ALSA

    # Limpieza: fechas que ya no se vigilan y han pasado
    for iso in list(dates_state):
        if iso not in config.get("dates", []) and date.fromisoformat(iso) < today:
            del dates_state[iso]
            changed = True
    return changed


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def commit_state():
    git("add", "data/state.json")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-m", "Actualizar estado de los buses")
    for _ in range(3):
        if git("pull", "--rebase", "-q").returncode == 0 and git("push", "-q").returncode == 0:
            return
        time.sleep(3)
    print("No he podido hacer push del estado")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if os.environ.get("TEST_TELEGRAM") == "true":
        telegram("✅ <b>Vigía bus conectado</b>\n"
                 "Te avisaré aquí cuando se libere el de las 18:00 Burgos → Valladolid.")
        return
    # MAX_MINUTES > 0: modo vigilante, repite rondas hasta agotar ese tiempo
    max_minutes = float(os.environ.get("MAX_MINUTES", "0"))
    rounds = int(os.environ.get("ROUNDS", "1"))
    gap = int(os.environ.get("ROUND_GAP", "120"))
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    deadline = time.monotonic() + max_minutes * 60
    alsa = Alsa()

    i = 0
    while True:
        if in_ci and i > 0:
            git("pull", "--rebase", "-q")  # coger fechas nuevas añadidas desde el dashboard
        config = load_json(CONFIG, {})
        state = load_json(STATE, {})
        if check_once(alsa, config, state):
            state["updated"] = now_iso()
            save_json(STATE, state)
            if in_ci:
                commit_state()
        i += 1
        more = time.monotonic() + gap < deadline if max_minutes else i < rounds
        if not more:
            break
        time.sleep(gap)

if __name__ == "__main__":
    sys.exit(main())
