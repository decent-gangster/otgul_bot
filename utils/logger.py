import logging
import sys


def setup_logging() -> None:
    """
    Настраивает логирование для всего приложения.
    Fly.io автоматически собирает stdout — дополнительных настроек не нужно.
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # Приглушаем шумные библиотеки
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)
