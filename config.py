from dataclasses import dataclass
from environs import Env

env = Env()
env.read_env()


@dataclass
class Config:
    bot_token: str
    admin_ids: list[int]
    group_id: int


def load_config() -> Config:
    return Config(
        bot_token=env.str("BOT_TOKEN"),
        admin_ids=list(map(int, env.list("ADMIN_IDS"))),
        group_id=env.int("GROUP_ID")
    )
