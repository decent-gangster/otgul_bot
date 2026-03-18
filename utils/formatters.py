from database.models import TimeOffRequest


def format_request_duration(req: TimeOffRequest) -> str:
    """Возвращает строку длительности заявки: '2 д.' или '4 ч.'"""
    if req.hours:
        h = req.hours
        return f"{h:.0f} ч." if h == int(h) else f"{h:.1f} ч."
    days = (req.end_date - req.start_date).days + 1
    return f"{days} д."


def format_request_period(req: TimeOffRequest) -> str:
    """Возвращает строку периода: '20.03.2026 — 21.03.2026' или '20.03.2026, 10:00–14:00'"""
    start = req.start_date.strftime("%d.%m.%Y")
    if req.hours and req.time_from and req.time_to:
        return f"{start}, {req.time_from}–{req.time_to}"
    if req.hours:
        return f"{start} ({req.hours:.0f} ч.)"
    end = req.end_date.strftime("%d.%m.%Y")
    return f"{start} — {end}"
