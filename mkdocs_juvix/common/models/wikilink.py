from typing import Optional

from .loc import FileLoc


class WikiLink:
    html_path: Optional[str]

    def __init__(
        self,
        page: str,
        hint: Optional[str] = None,
        anchor: Optional[str] = None,
        display: Optional[str] = None,
        loc: Optional[FileLoc] = None,
        html_path: Optional[str] = None,
    ):
        self.page: str = self._normalize_text(page)
        self.hint: Optional[str] = hint.strip() if hint else None
        self.anchor: Optional[str] = anchor.strip() if anchor else None
        self.display: Optional[str] = display.strip() if display else None
        self.loc: Optional[FileLoc] = loc
        self.html_path: Optional[str] = html_path

    def _normalize_text(
        self, text: str, strip: bool = True, join_with: str = " ", sep: str = "\n"
    ) -> str:
        if strip:
            text = text.strip()
        return (
            text.replace(" ", " ")
            .replace("\n", " ")
            .replace("\t", " ")
            .replace("-", " ")
        )

    def __hash__(self):
        return hash(self.page)

    @property
    def text(self):
        _text = self.display if self.display else self.page
        return _text

    def __repr__(self):
        return f"""
    WikiLink:
      Page: {self.page}
      Hint: {self.hint if self.hint else 'None'}
      Anchor: {self.anchor if self.anchor else 'None'}
      Display: {self.display if self.display else 'None'}
      Loc: {str(self.loc) if self.loc else 'None'}
      Html_path: {self.html_path if self.html_path else 'None'}
    """

    def markdown(self) -> str:
        if self.html_path:
            return f"[{self.text}]({self.html_path}{'#' + self.anchor if self.anchor else ''})"
        else:
            return f"{self.text}"
