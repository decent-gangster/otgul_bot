from database.models import TimeOffRequest


def format_request_duration(req: TimeOffRequest) -> str:
    """Возвращает строку длительности заявки: '2 д.' или '4 ч.'"""
    if req.hours:
        return f"{req.hours:.0f} ч."
    days = (req.end_date - req.start_date).days + 1
    return f"{days} д."


def format_request_period(req: TimeOffRequest) -> str:
    """Возвращает строку периода: '20.03.2026 — 21.03.2026' или '20.03.2026 (4 ч.)'"""
    start = req.start_date.strftime("%d.%m.%Y")
    if req.hours:
        return f"{start} ({req.hours:.0f} ч.)"
    end = req.end_date.strftime("%d.%m.%Y")
    return f"{start} — {end}"
