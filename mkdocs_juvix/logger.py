import os
import logging
from colorama import Fore, Style  # type: ignore

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
print(f"{Fore.GREEN}DEBUG: {DEBUG}")

class Logger(logging.Logger):
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        super().__init__(logger.name, logger.level)
        
    def info(self, msg, *args, **kwargs):
        if DEBUG:
            self.debug(msg, *args, **kwargs)
        else:
            super().info(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        if DEBUG:
            print("-"*100)
            print(msg, *args, **kwargs)
            clear_line(2)
        else:
            super().debug(msg, *args, **kwargs)

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, Any]:
        """
        Process the message.

        Arguments:
            msg: The message:
            kwargs: Remaining arguments.

        Returns:
            The processed message.
        """
        return f"{self.prefix}: {msg}", kwargs
def get_plugin_logger(name: str) -> PrefixedLogger:
    """
    Return a logger for plugins.

    Arguments:
        name: The name to use with `logging.getLogger`.

    Returns:
        A logger configured to work well in MkDocs,
            prefixing each message with the plugin package name.

    Example:
        ```python
        from mkdocs.plugins import get_plugin_logger

        log = get_plugin_logger(__name__)
        log.info("My plugin message")
        ```
    """
    logger = logging.getLogger(f"mkdocs.plugins.{name}")
    setattr(logger, "info", lambda msg: getattr(logger, "info")(msg))
    return PrefixedLogger(name.split(".", 1)[0], logger)

log = get_plugin_logger(f"{Fore.BLUE}juvix_mkdocs{Style.RESET_ALL}")

def clear_screen():
    if os.getenv("DEBUG", "false").lower() != "true":
        print("\033[H\033[J", end="", flush=True)

def clear_line(n=1):
    if os.getenv("DEBUG", "false").lower() != "true":
        for _ in range(n):
            print("\033[A", end="", flush=True)
        print("\033[K", end="\r", flush=True)
