import os
import logging
from typing import Any, MutableMapping
from colorama import Fore, Style  # type: ignore

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
print(f"{Fore.GREEN}DEBUG: {DEBUG}")

class Logger(logging.Logger):
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        super().__init__(logger.name, logger.level)
        
    def info(self, msg, *args, **kwargs):
        print("-"*100)
        print(msg, *args, **kwargs)
        clear_line()

    def debug(self, msg, *args, **kwargs):
        if DEBUG:
            print("-"*100)
            print(msg, *args, **kwargs)
        else:
            clear_line()
            print(msg, *args, **kwargs)
            # super().debug(msg, *args, **kwargs)

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, Any]:
        return f"juvix-mkdocs: {msg}", kwargs


def get_plugin_logger(name: str) -> Logger:
    logger = logging.getLogger(f"mkdocs.plugins.{name}")
    return Logger(logger)

log = get_plugin_logger(f"{Fore.BLUE}juvix_mkdocs{Style.RESET_ALL}")


def clear_screen():
    if os.getenv("DEBUG", "false").lower() != "true":
        print("\033[H\033[J", end="", flush=True)

def clear_line():
    if os.getenv("DEBUG", "false").lower() != "true":
        print("\033[A", end="", flush=True)
        print("\033[K", end="\r", flush=True)
