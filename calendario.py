"""Dibuja el estado de las fechas vigiladas como una imagen de calendario (PNG) para Telegram."""
import calendar
import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
WEEK = ["L", "M", "X", "J", "V", "S", "D"]

BG, INK, MUTED, FAINT = "#ffffff", "#1f2328", "#8b9096", "#d9dcdf"
STYLE = {  # estado -> (relleno, borde, texto, leyenda)
    "V": ("#1f9d55", None, "#ffffff", "18:00 con plaza"),
    "F": ("#d64545", None, "#ffffff", "Completo"),
    "none": ("#6b7178", None, "#ffffff", "Sin bus en la franja"),
    "nosale": (None, "#b9bec4", "#6b7178", "Aún sin billetes"),
}

CELL, GAP, COLS, PAD, MONTH_GAP = 66, 6, 2, 44, 52


def _font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf"] if bold else ["DejaVuSans.ttf", "arial.ttf"])
    for name in names:
        for path in (name, f"/usr/share/fonts/truetype/dejavu/{name}"):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default(size)


def _center(draw, box, text, font, fill):
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) / 2, (y0 + y1) / 2), text, font=font, fill=fill, anchor="mm")


def render(statuses, today, updated=None):
    """statuses: {date: "V" | "F" | "none" | "nosale"}. Devuelve los bytes del PNG."""
    months = sorted({(d.year, d.month) for d in statuses})
    rows = -(-len(months) // COLS)
    month_w = 7 * CELL + 6 * GAP
    month_h = 48 + 34 + 6 * (CELL + GAP)
    header_h, legend_h = 110, 2 * 48 + 20
    width = PAD * 2 + COLS * month_w + (COLS - 1) * MONTH_GAP
    height = PAD + header_h + rows * month_h + (rows - 1) * MONTH_GAP // 2 + legend_h + PAD

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    f_title, f_sub = _font(40, True), _font(24)
    f_month, f_week, f_day = _font(28, True), _font(20, True), _font(24, True)
    f_day_plain, f_legend = _font(22), _font(24)

    d.text((PAD, PAD), "Bus 18:00  Burgos – Valladolid", font=f_title, fill=INK)
    if updated:
        d.text((PAD, PAD + 56), f"Actualizado {updated}", font=f_sub, fill=MUTED)

    for i, (year, month) in enumerate(months):
        ox = PAD + (i % COLS) * (month_w + MONTH_GAP)
        oy = PAD + header_h + (i // COLS) * (month_h + MONTH_GAP // 2)
        d.text((ox, oy), f"{MONTHS[month - 1].capitalize()} {year}", font=f_month, fill=INK)
        for c, w in enumerate(WEEK):
            _center(d, (ox + c * (CELL + GAP), oy + 48, ox + c * (CELL + GAP) + CELL, oy + 78),
                    w, f_week, MUTED)
        for r, week in enumerate(calendar.Calendar().monthdatescalendar(year, month)):
            for c, day in enumerate(week):
                if day.month != month:
                    continue
                x, y = ox + c * (CELL + GAP), oy + 82 + r * (CELL + GAP)
                box = (x, y, x + CELL, y + CELL)
                st = statuses.get(day)
                if st:
                    fill, outline, color, _ = STYLE[st]
                    d.rounded_rectangle(box, radius=12, fill=fill, outline=outline,
                                        width=3 if outline else 0)
                    _center(d, box, str(day.day), f_day, color)
                else:
                    _center(d, box, str(day.day), f_day_plain, FAINT if day < today else MUTED)
                if day == today:
                    d.rounded_rectangle((x - 3, y - 3, x + CELL + 3, y + CELL + 3), radius=14,
                                        outline=INK, width=3)

    # Leyenda en dos columnas
    ly = height - PAD - legend_h + 20
    for i, (fill, outline, _, label) in enumerate(STYLE.values()):
        x = PAD + (i % 2) * (width - 2 * PAD) // 2
        y = ly + (i // 2) * 48
        d.rounded_rectangle((x, y, x + 32, y + 32), radius=8, fill=fill, outline=outline,
                            width=3 if outline else 0)
        d.text((x + 46, y + 16), label, font=f_legend, fill=INK, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


if __name__ == "__main__":  # vista previa local: python calendario.py
    import checker
    cfg, st = checker.load_json(checker.CONFIG, {}), checker.load_json(checker.STATE, {})
    out = checker.ROOT / "calendario.png"
    out.write_bytes(render(checker.date_statuses(cfg, st), date.today(), "ahora"))
    print(out)
