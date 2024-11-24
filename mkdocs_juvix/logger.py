import logging
from typing import Any, MutableMapping

from colorama import Fore, Style  # type: ignore


class PrefixedLogger(logging.LoggerAdapter):
    """A logger adapter to prefix log messages."""

    def __init__(self, prefix: str, logger: logging.Logger) -> None:
        """
        Initialize the logger adapter.

        Arguments:
            prefix: The string to insert in front of every message.
            logger: The logger instance.
        """
        super().__init__(logger, {})
        self.prefix = prefix

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
    setattr(logger, "info", lambda msg: clear_screen() and getattr(logger, "info")(msg))
    return PrefixedLogger(name.split(".", 1)[0], logger)


log = get_plugin_logger(f"{Fore.BLUE}juvix_mkdocs{Style.RESET_ALL}")


def clear_screen():
    print("\033[H\033[J", end="", flush=True)


def clear_line():
    print("\033[A", end="", flush=True)
    print("\033[K", end="\r", flush=True)
