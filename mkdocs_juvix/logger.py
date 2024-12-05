import os
import logging
from colorama import Fore, Style  # type: ignore

log = logging.getLogger("mkdocs.plugins.juvix")

DEBUG = bool(os.getenv("DEBUG", "false").lower()) == "true"
print(f"{Fore.GREEN}DEBUG: {DEBUG}")

def clear_screen():
    if os.getenv("DEBUG", "false").lower() != "true":
        print("\033[H\033[J", end="", flush=True)

def clear_line(n=1):
    if os.getenv("DEBUG", "false").lower() != "true":
        for _ in range(n):
            print("\033[A", end="", flush=True)
        print("\033[K", end="\r", flush=True)
