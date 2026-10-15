# 🚌 Vigía bus ALSA Burgos → Valladolid (18:00)

Comprueba cada pocos minutos en la web de ALSA si hay plazas en el bus de las 18:00 (o refuerzos en esa franja)
para las fechas elegidas y avisa por Telegram. Dashboard en GitHub Pages para elegir fechas y ver el historial.

## Cómo funciona
- `checker.py` replica la búsqueda de alsa.es (origen 90593 = Burgos, destino 90305 = Valladolid).
  Cada servicio aparece como `V` (a la venta), `F` (completo) o desaparece de la lista.
- `.github/workflows/check.yml` corre en modo vigilante: una ejecución de ~5h40 que comprueba cada 2 min y se relanza sola; un cron cada 30 min hace de respaldo.
- Estado e historial de cambios en `data/state.json`; fechas y franja horaria en `config.json`.
- `docs/index.html` es el dashboard (GitHub Pages).

## Configurar Telegram
1. En Telegram habla con **@BotFather** → `/newbot` → copia el token.
2. Escribe cualquier cosa a tu bot nuevo.
3. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia `chat.id`.
4. En GitHub → Settings → Secrets and variables → Actions: crea `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`.

## Token para el dashboard
GitHub → Settings → Developer settings → Fine-grained tokens → nuevo token solo para este repo con
**Contents: Read and write** y **Actions: Read and write**. Pégalo en ⚙️ Ajustes del dashboard (se guarda solo en tu navegador).

## Probar en local
```
pip install -r requirements.txt
python checker.py
```
