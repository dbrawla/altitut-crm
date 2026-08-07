"""
Template rendering — port of internal/manager rendering + models template compile.

listmonk templates (campaign bodies, user templates, system emails) are written
in Go text/template syntax. This module translates the subset listmonk uses
into Jinja2 at render time, so the original .tpl/.html files and existing
user templates keep working unchanged:

    {{ .Subscriber.FirstName }}            -> {{ Subscriber.FirstName }}
    {{ template "content" . }}             -> {{ content }}
    {{ TrackLink "https://x" . }}          -> {{ TrackLink("https://x") }}
    {{ if eq .Type "public" }}...{{ end }} -> {% if Type == "public" %}...{% endif %}
    {{ range $i, $l := .Lists }}           -> {% for l in Lists %} (inner dots -> l)
    {{ index . "ID" }}                     -> {{ index(DOT, "ID") }}

Unsupported constructs (sprig functions, `with`, complex pipelines) raise a
render error that is logged per message — same failure mode as a broken Go
template upstream.
"""

from __future__ import annotations

import functools
import html as htmllib
import logging
import re
from collections.abc import Callable
from datetime import UTC
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateError
from markupsafe import Markup

from app import db, settings

log = logging.getLogger("listmonk")

DUMMY_UUID = "00000000-0000-0000-0000-000000000000"

# ---------------------------------------------------------------------------
# Go template -> Jinja2 translation
# ---------------------------------------------------------------------------

_COMPARATORS = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}

_token_re = re.compile(
    r"""("(?:[^"\\]|\\.)*")|(\()|(\))|([^\s()]+)""",
)


def _tokenize(expr: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in _token_re.finditer(expr)]


def _conv_atom(tok: str, dot_var: str) -> str:
    if tok.startswith('"'):
        return tok
    if tok == ".":
        return dot_var
    if tok.startswith("$"):
        return tok[1:] or dot_var
    if tok.startswith("."):
        return f"{dot_var}.{tok[1:]}" if dot_var != "DOT" else tok[1:]
    return tok


class _ExprParser:
    """Converts a Go template expression (prefix calls) to a Jinja2 expression."""

    def __init__(self, tokens: list[str], dot_var: str) -> None:
        self.toks = tokens
        self.i = 0
        self.dot = dot_var

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> str:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse_operand(self) -> str:
        t = self.next()
        if t == "(":
            inner = self.parse_call()
            if self.peek() == ")":
                self.next()
            return f"({inner})"
        return _conv_atom(t, self.dot)

    def parse_call(self) -> str:
        """Parse `func a b c` or a lone operand."""
        if self.peek() is None:
            return ""
        first = self.next()
        if first == "(":
            inner = self.parse_call()
            if self.peek() == ")":
                self.next()
            first = f"({inner})"
            if self.peek() is None:
                return first
        args: list[str] = []
        while self.peek() is not None and self.peek() != ")":
            args.append(self.parse_operand())
        if first in _COMPARATORS and len(args) == 2:
            return f"{args[0]} {_COMPARATORS[first]} {args[1]}"
        if first.startswith('"') or first.startswith("(") or (first.startswith(_conv_atom(".", self.dot)[:1]) and not args):
            return _conv_atom(first, self.dot)
        name = _conv_atom(first, self.dot)
        if not args:
            # Bare variable/field reference.
            return name
        # Go passes the dot as a trailing arg to msg-scoped funcs; drop it.
        args = [a for a in args if a != self.dot or name == "index"]
        return f"{name}({', '.join(args)})"


def _conv_expr(expr: str, dot_var: str) -> str:
    expr = expr.strip()
    # Method calls like L.Ts "key" -> L.Ts("key") are handled by parse_call.
    return _ExprParser(_tokenize(expr), dot_var).parse_call()


@functools.lru_cache(maxsize=512)
def go2jinja(src: str) -> str:
    """Translate a Go template string into a Jinja2 template string."""
    out: list[str] = []
    pos = 0
    stack: list[str] = []  # "if" | "for" | "define"
    dots: list[str] = ["DOT"]

    for m in re.finditer(r"\{\{-?\s*(.*?)\s*-?\}\}", src, re.S):
        out.append(src[pos : m.start()])
        pos = m.end()
        stmt = m.group(1).strip()

        if stmt.startswith("/*") or stmt.startswith("comment"):
            continue
        if stmt.startswith("define "):
            stack.append("define")
            continue  # define wrappers are stripped; the file is split by caller
        if stmt == "end":
            what = stack.pop() if stack else "if"
            if what == "for":
                dots.pop()
                out.append("{% endfor %}")
            elif what == "if":
                out.append("{% endif %}")
            continue
        if stmt == "else":
            out.append("{% else %}")
            continue
        if stmt.startswith("else if "):
            out.append("{% elif " + _conv_expr(stmt[8:], dots[-1]) + " %}")
            continue
        if stmt.startswith("if "):
            stack.append("if")
            out.append("{% if " + _conv_expr(stmt[3:], dots[-1]) + " %}")
            continue
        if stmt.startswith("range "):
            stack.append("for")
            body = stmt[6:].strip()
            var = None
            if ":=" in body:
                head, body = body.split(":=", 1)
                names = [v.strip().lstrip("$") for v in head.split(",")]
                var = names[-1] or "item"
            coll = _conv_expr(body.strip(), dots[-1])
            var = var or "item"
            dots.append(var)
            out.append(f"{{% for {var} in {coll} %}}")
            continue
        if stmt.startswith("with "):
            # Approximate `with` as `if` + dot rebinding to the expression.
            stack.append("if")
            expr = _conv_expr(stmt[5:], dots[-1])
            out.append(f"{{% if {expr} %}}")
            continue
        if stmt.startswith("template "):
            mm = re.match(r'template\s+"([^"]+)"', stmt)
            if mm:
                name = mm.group(1)
                if name == "content":
                    out.append("{{ content }}")
                else:
                    out.append(f'{{% include "{name}" %}}')
            continue

        out.append("{{ " + _conv_expr(stmt, dots[-1]) + " }}")

    out.append(src[pos:])
    return "".join(out)


def split_defines(src: str) -> dict[str, str]:
    """Split a Go template file with {{ define "x" }}...{{ end }} blocks into
    a name->body map. Content outside defines goes under ""."""
    parts: dict[str, str] = {}
    depth = 0
    name: str | None = None
    pos = 0
    for m in re.finditer(r"\{\{-?\s*(.*?)\s*-?\}\}", src, re.S):
        stmt = m.group(1).strip()
        if stmt.startswith("define ") and depth == 0:
            mm = re.match(r'define\s+"([^"]+)"', stmt)
            name = mm.group(1) if mm else "unnamed"
            depth = 1
            pos = m.end()
        elif name is not None:
            if stmt.startswith(("if ", "range ", "with ", "define ", "block ")):
                depth += 1
            elif stmt == "end":
                depth -= 1
                if depth == 0:
                    parts[name] = src[pos : m.start()]
                    name = None
    if not parts:
        parts[""] = src
    return parts


# ---------------------------------------------------------------------------
# Jinja environment + template functions
# ---------------------------------------------------------------------------


class _Loader(BaseLoader):
    """Loads named sub-templates (header/footer from base.html) on demand."""

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, Callable[[], bool] | None]:
        base = (db.ROOT / "static" / "email-templates" / "base.html").read_text(encoding="utf-8")
        parts = split_defines(base)
        if template not in parts:
            raise TemplateError(f"unknown template: {template}")
        return go2jinja(parts[template]), None, lambda: True


class L10n:
    """The `L` template object: L.T "key" / L.Ts "key" i18n lookups."""

    def __init__(self) -> None:
        self._map: dict[str, str] | None = None

    def _lang(self) -> dict[str, str]:
        if self._map is None:
            from app.routers.admin import load_lang

            try:
                self._map = load_lang(settings.get("app.lang", "en"))
            except Exception:
                # Fall back to raw keys rather than failing the whole render.
                log.warning("could not load i18n strings; using keys", exc_info=True)
                self._map = {}
        return self._map

    def T(self, key: str) -> str:
        return self._lang().get(key, key)

    def Ts(self, key: str, *pairs: str) -> str:
        s = self._lang().get(key, key)
        for i in range(0, len(pairs) - 1, 2):
            s = s.replace("{" + pairs[i] + "}", pairs[i + 1])
        return s


def _make_env() -> Environment:
    env = Environment(loader=_Loader(), autoescape=True, cache_size=400)
    env.globals["L"] = L10n()
    env.globals["index"] = lambda obj, key, default="": (obj or {}).get(key, default)
    env.globals["Date"] = _fn_date
    env.globals["Safe"] = lambda s: Markup(s or "")
    return env


def _fn_date(layout: str = "") -> str:
    from datetime import datetime

    # The app runs with TZ=Etc/UTC; be explicit rather than relying on it.
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d %H:%M" if not layout else "%Y-%m-%d")


_env = _make_env()


def _urls() -> dict[str, str]:
    root = (settings.get("app.root_url") or "").rstrip("/")
    return {
        "root": root,
        "unsub": root + "/subscription/{camp_uuid}/{sub_uuid}",
        "optin": root + "/subscription/optin/{sub_uuid}",
        "message": root + "/campaign/{camp_uuid}/{sub_uuid}",
        "view_pixel": root + "/campaign/{camp_uuid}/{sub_uuid}/px.png",
        "link": root + "/link/{link_uuid}/{camp_uuid}/{sub_uuid}",
        "archive": root + "/archive",
    }


def subscriber_ctx(sub: dict[str, Any] | None) -> dict[str, Any]:
    sub = sub or {
        "uuid": DUMMY_UUID,
        "email": "demo@listmonk.app",
        "name": "Demo Subscriber",
        "attribs": {},
        "status": "enabled",
    }
    name = (sub.get("name") or "").strip()
    first, _, last = name.partition(" ")
    return {
        "UUID": sub.get("uuid"),
        "Email": sub.get("email"),
        "Name": name,
        "FirstName": first or name,
        "LastName": last,
        "Status": sub.get("status"),
        "Attribs": sub.get("attribs") or {},
    }


def campaign_ctx(camp: dict[str, Any]) -> dict[str, Any]:
    return {
        "UUID": camp.get("uuid"),
        "Name": camp.get("name"),
        "Subject": camp.get("subject"),
        "FromEmail": camp.get("from_email"),
        "Tags": camp.get("tags") or [],
        "Attribs": camp.get("attribs") or {},
    }


async def _track_link(url: str, camp_uuid: str, sub_uuid: str) -> str:
    import uuid as uuidlib

    link_uuid = await db.fetchval("create-link", str(uuidlib.uuid4()), url)
    return _urls()["link"].format(link_uuid=link_uuid, camp_uuid=camp_uuid, sub_uuid=sub_uuid)


_TRACKLINK_RE = re.compile(r"(https?://[^\"'\s>]+?)@TrackLink", re.I)


async def render_message(
    camp: dict[str, Any],
    sub: dict[str, Any] | None,
    preview: bool = False,
) -> tuple[str, str, str]:
    """Render (subject, html_body, text_body) for one subscriber — the port of
    manager.NewCampaignMessage + Render."""
    urls = _urls()
    disable_tracking = settings.get("privacy.disable_tracking", False)
    individual = settings.get("privacy.individual_tracking", False)

    sub_uuid = (sub or {}).get("uuid", DUMMY_UUID)
    track_sub_uuid = sub_uuid if individual else DUMMY_UUID
    camp_uuid = camp.get("uuid", DUMMY_UUID)

    unsub_url = urls["unsub"].format(camp_uuid=camp_uuid, sub_uuid=sub_uuid)

    # Collected async link registrations (Jinja is sync; registered after).
    pending_links: list[str] = []

    def TrackLink(url: str) -> str:
        if disable_tracking or preview:
            return url
        pending_links.append(url)
        return f"%%TRACKLINK:{len(pending_links) - 1}%%"

    def TrackView() -> Markup:
        if disable_tracking or preview:
            return Markup("")
        px = urls["view_pixel"].format(camp_uuid=camp_uuid, sub_uuid=track_sub_uuid)
        return Markup(f'<img src="{px}" alt="" />')

    ctx: dict[str, Any] = {
        "DOT": {},
        "Subscriber": subscriber_ctx(sub),
        "Campaign": campaign_ctx(camp),
        # Go's template engine auto-calls niladic functions, Jinja does not:
        # `{{ UnsubscribeURL }}` would render the function object itself. These
        # take no arguments in Go, so they're passed as plain values. TrackLink
        # takes a URL argument and stays callable.
        "TrackLink": TrackLink,
        "TrackView": TrackView(),
        "UnsubscribeURL": unsub_url,
        "ManageURL": unsub_url + "?manage=true",
        "OptinURL": urls["optin"].format(sub_uuid=sub_uuid),
        "MessageURL": urls["message"].format(camp_uuid=camp_uuid, sub_uuid=sub_uuid),
        "ArchiveURL": urls["archive"],
        "RootURL": urls["root"],
    }
    ctx["DOT"] = ctx

    # 1) Subject. Feed the rendered value back into the context so that
    # `{{ .Campaign.Subject }}` in the body/template (the default template puts
    # it in <title>) shows the rendered subject, not the raw placeholders.
    subject = _render_str(camp.get("subject") or "", ctx)
    ctx["Campaign"]["Subject"] = subject

    # 2) Content (campaign body).
    body_src = camp.get("body") or ""
    content = _render_str(body_src, ctx)
    if camp.get("content_type") == "markdown":
        import markdown as md

        content = md.markdown(content, extensions=["tables", "fenced_code"])

    # 3) Wrap in the campaign template ({{ template "content" . }} slot).
    tpl_body = camp.get("template_body") or ""
    if tpl_body and camp.get("content_type") != "plain":
        ctx["content"] = Markup(content)
        html_body = _render_str(tpl_body, ctx)
    else:
        html_body = content

    # 4) @TrackLink suffixes (same effect as the original pre-compile rewrite).
    def _tl(mm: re.Match[str]) -> str:
        return TrackLink(mm.group(1))

    html_body = _TRACKLINK_RE.sub(_tl, html_body)
    subject = _TRACKLINK_RE.sub(_tl, subject)

    # Register collected links and substitute the placeholders.
    for i, url in enumerate(pending_links):
        tracked = await _track_link(url, camp_uuid, track_sub_uuid)
        html_body = html_body.replace(f"%%TRACKLINK:{i}%%", tracked)

    # 5) Plain-text alternative.
    text_body = camp.get("altbody") or ""
    if not text_body:
        text_body = html_to_text(html_body)

    return subject, html_body, text_body


def _render_str(src: str, ctx: dict[str, Any]) -> str:
    if "{{" not in src and "{%" not in src:
        return src
    tpl = _env.from_string(go2jinja(src))
    return tpl.render(**ctx)


async def render_campaign_preview(camp: dict[str, Any], sub: dict[str, Any] | None) -> str:
    _, html_body, _ = await render_message(camp, sub, preview=True)
    return html_body


def render_tx(
    body: str, subject: str, sub: dict[str, Any] | None, data: dict[str, Any]
) -> tuple[str, str]:
    """Render a transactional template — port of models.TxMessage.Render.

    The context is {Subscriber, Tx}, where `.Tx.Data.<key>` exposes the caller's
    arbitrary params. Returns (subject, body).
    """
    ctx: dict[str, Any] = {
        "DOT": {},
        "Subscriber": subscriber_ctx(sub),
        "Tx": {"Data": data or {}, "Subject": subject},
    }
    ctx["DOT"] = ctx
    rendered_subject = _render_str(subject or "", ctx)
    ctx["Tx"]["Subject"] = rendered_subject
    return rendered_subject, _render_str(body or "", ctx)


def render_system_email(name: str, data: dict[str, Any]) -> str:
    """Render static/email-templates/<name>.html (Go syntax) with `data`."""
    src = (db.ROOT / "static" / "email-templates" / f"{name}.html").read_text(encoding="utf-8")
    parts = split_defines(src)
    body = parts.get(name) or parts.get("") or src
    # Values, not lambdas — Jinja renders a bare `{{ LogoURL }}` as the object
    # itself, which put "<function ... at 0x...>" into the <img src>.
    ctx: dict[str, Any] = {
        "DOT": data,
        "RootURL": (settings.get("app.root_url") or "").rstrip("/"),
        "LogoURL": settings.get("app.logo_url") or "",
        "SiteName": settings.get("app.site_name", "listmonk"),
    }
    ctx.update(data)
    tpl = _env.from_string(go2jinja(body))
    return tpl.render(**ctx)


# ---------------------------------------------------------------------------
# HTML converters
# ---------------------------------------------------------------------------

_tag_re = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_ws_re = re.compile(r"[ \t]*\n[ \t\n]*")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", s)
    s = _tag_re.sub("", s)
    s = htmllib.unescape(s)
    return _ws_re.sub("\n", s).strip()


def html_to_markdown(s: str) -> str:
    # ponytail: minimal converter for the content-type switcher; the frontend
    # does rich conversion client-side with turndown.
    for i in range(6, 0, -1):

        def _heading(m: re.Match[str], level: int = i) -> str:
            return "#" * level + " " + m.group(1) + "\n\n"

        s = re.sub(rf"(?is)<h{i}[^>]*>(.*?)</h{i}>", _heading, s)
    s = re.sub(r"(?is)<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", s)
    s = re.sub(r"(?is)<(i|em)[^>]*>(.*?)</\1>", r"*\2*", s)
    s = re.sub(r'(?is)<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", s)
    s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", r"- \1\n", s)
    return html_to_text(s)


if __name__ == "__main__":
    # Self-check of the Go->Jinja translator on the constructs listmonk uses.
    assert go2jinja("Hi {{ .Subscriber.FirstName }}!") == "Hi {{ Subscriber.FirstName }}!"
    assert go2jinja('{{ template "content" . }}') == "{{ content }}"
    assert go2jinja('{{ TrackLink "https://x" . }}') == '{{ TrackLink("https://x") }}'
    assert go2jinja("{{ UnsubscribeURL . }}") == "{{ UnsubscribeURL() }}"
    assert (
        go2jinja('{{ if eq .Type "public" }}A{{ else }}B{{ end }}')
        == '{% if Type == "public" %}A{% else %}B{% endif %}'
    )
    assert (
        go2jinja("{{ range $i, $l := .Lists }}{{ .Name }}{{ end }}")
        == "{% for l in Lists %}{{ l.Name }}{% endfor %}"
    )
    assert go2jinja('{{ index . "ID" }}') == '{{ index(DOT, "ID") }}'
    assert (
        go2jinja('{{ if ne (index . "Reason") "" }}x{{ end }}')
        == '{% if (index(DOT, "Reason")) != "" %}x{% endif %}'
    )
    assert go2jinja('{{ L.Ts "email.optin.confirmSubTitle" }}') == '{{ L.Ts("email.optin.confirmSubTitle") }}'
    print("tmpl self-check OK")
