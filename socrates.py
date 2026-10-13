import re
import textwrap

from google.genai import types
from pydantic import BaseModel

import config
import llm_client
import usage
from prompts import TWIN_PROMPT, build_system_prompt, concepts_text, graph_prompt


class InvalidProblem(Exception):
    """The input isn't a real problem statement. Message is safe to show."""


class ConceptNode(BaseModel):
    id: str
    label: str
    requires: list[str]


class ConceptGraph(BaseModel):
    nodes: list[ConceptNode]


class MapResult(BaseModel):
    """What the model returns for the validate + build-map call."""
    is_valid_problem: bool
    rejection_reason: str
    nodes: list[ConceptNode]


class NodeUpdate(BaseModel):
    node_id: str
    status: str  # "green" or "red"


class TutorTurn(BaseModel):
    reply: str
    misconception: str
    topic: str
    node_updates: list[NodeUpdate]


class TwinProblem(BaseModel):
    problem: str
    trap: str


COLORS = {"grey": "#d9d9d9", "green": "#7bd88f", "red": "#ff8a80"}

# problem text -> ConceptGraph (accepted) or str (rejection reason). Saves repeat calls.
_GRAPH_CACHE: dict[str, "ConceptGraph | str"] = {}

_FENCE = re.compile(r"```.*?(```|$)", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


# ---------- sanitizing helpers (model output is untrusted) ----------
def _clean(text: str, limit: int) -> str:
    text = re.sub(r'["\\<>{}\[\]|&`*_#]', "", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _nid(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")[:30]


def sanitize_reply(text: str, level: int) -> str:
    """Hard guard: remove tracking images, and code blocks before the solution unlock."""
    text = _IMAGE.sub("[image removed]", text or "")
    if level < 4:
        text = _FENCE.sub("*[code hidden until you unlock the solution]*", text)
    return text.strip()


def precheck_problem(text: str) -> str | None:
    """Free, instant filter for obvious junk. Returns a rejection reason, or None."""
    t = (text or "").strip()
    words = re.findall(r"\w+", t.lower())
    if len(t) < config.MIN_PROBLEM_CHARS or len(words) < 4:
        return "That's too short to be a problem statement. Paste the full problem: what the input is and what to compute."
    if len(set(words)) < 4:
        return "That text is mostly repeated words. Paste a real problem statement."
    if sum(c.isalpha() for c in t) / len(t) < 0.25:
        return "That doesn't look like a problem statement. Paste the problem text."
    return None


def normalize_graph(raw: MapResult) -> ConceptGraph | None:
    """Clean ids/labels/edges. Returns None if fewer than 2 usable concepts remain."""
    kept, ids = [], set()
    for n in raw.nodes:
        nid = _nid(n.id)
        if not nid or nid in ids:
            continue
        ids.add(nid)
        kept.append((nid, _clean(n.label, 40) or nid, n.requires))
        if len(kept) >= config.MAX_CONCEPTS:
            break
    if len(kept) < 2:
        return None
    return ConceptGraph(
        nodes=[
            ConceptNode(
                id=i,
                label=label,
                requires=[
                    r
                    for r in dict.fromkeys(_nid(x) for x in req)
                    if r in ids and r != i
                ],
            )
            for i, label, req in kept
        ]
    )


class Session:
    MAX_HINT_LEVEL = 3

    def __init__(
        self,
        problem: str,
        language: str = "Python",
        trap_note: str = "",
        round_no: int = 1,
        calls: int = 0,
    ):
        self.problem = problem.strip()[: config.MAX_PROBLEM_CHARS]
        self.language = language if language in config.LANGUAGES else "Python"
        self.trap_note = trap_note
        self.round_no = round_no
        self.calls = calls
        self.level = 1
        self.history: list[tuple[str, str]] = []  # (role, text) sent to the model
        self.log: list[tuple[str, str]] = []  # (role, text) shown in the UI
        self.misconceptions: list[str] = []
        self.topic = ""
        self.graph: ConceptGraph | None = None
        self.status: dict[str, str] = {}

    # ---------- model access with usage guardrails ----------
    def _ask(self, schema, contents, system, max_tokens):
        usage.check_and_count(self.calls)
        self.calls += 1
        return llm_client.generate_json(contents, system, schema, max_tokens)

    # ---------- validate the problem + build the concept map ----------
    def build_graph(self):
        reason = precheck_problem(self.problem)  # free: no API call for obvious junk
        if reason:
            raise InvalidProblem(reason)

        cached = _GRAPH_CACHE.get(self.problem)
        if isinstance(cached, str):
            raise InvalidProblem(cached)
        if cached is None:
            raw = self._ask(
                MapResult,
                f"Problem:\n{self.problem}",
                graph_prompt(),
                config.MAX_OUTPUT_TOKENS_CHAT,
            )
            if not raw.is_valid_problem:
                reason = _clean(raw.rejection_reason, 200) or (
                    "It needs a clear task: what the input is and what to compute."
                )
                if len(_GRAPH_CACHE) < 200:
                    _GRAPH_CACHE[self.problem] = reason
                raise InvalidProblem(reason)
            cached = normalize_graph(raw)
            if cached is None:  # model said "valid" but gave no usable map: never fake one
                raise llm_client.LLMError(
                    "I couldn't build a concept map for this problem. Try again or rephrase it."
                )
            if len(_GRAPH_CACHE) < 200:
                _GRAPH_CACHE[self.problem] = cached
        self.graph = cached
        self.status = {n.id: "grey" for n in cached.nodes}

    def map_dot(self) -> str:
        if not self.graph:
            return "digraph G {}"
        index = {n.id: f"n{i}" for i, n in enumerate(self.graph.nodes)}
        lines = [
            "digraph G {",
            "rankdir=LR;",
            'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=12];',
        ]
        for n in self.graph.nodes:
            label = "\\n".join(textwrap.wrap(n.label, 14)) or n.label
            color = COLORS[self.status.get(n.id, "grey")]
            lines.append(f'{index[n.id]} [label="{label}", fillcolor="{color}"];')
        for n in self.graph.nodes:
            for r in n.requires:
                if r in index:
                    lines.append(f"{index[r]} -> {index[n.id]};")
        lines.append("}")
        return "\n".join(lines)

    def progress(self) -> tuple[int, int]:
        total = len(self.status)
        green = sum(1 for s in self.status.values() if s == "green")
        return green, total

    # ---------- tutoring ----------
    @staticmethod
    def _window(messages):
        """Only resend the last N messages; the window must start with a user turn."""
        msgs = messages[-config.HISTORY_MESSAGES :]
        while msgs and msgs[0][0] != "user":
            msgs = msgs[1:]
        return [
            types.Content(role=role, parts=[types.Part(text=text)])
            for role, text in msgs
        ]

    def _turn(self, student_text: str, display_text: str | None, level: int) -> TutorTurn:
        student_text = student_text.strip()[: config.MAX_MESSAGE_CHARS]
        messages = self.history + [("user", student_text)]
        system = build_system_prompt(
            self.problem,
            level,
            self.language,
            concepts_text(self.graph, self.status),
            self.trap_note,
        )
        max_tokens = (
            config.MAX_OUTPUT_TOKENS_SOLUTION if level == 4 else config.MAX_OUTPUT_TOKENS_CHAT
        )
        # If this raises, nothing below runs: level, history and map stay unchanged.
        turn = self._ask(TutorTurn, self._window(messages), system, max_tokens)

        reply = sanitize_reply(turn.reply, level) or (
            "Let's slow down. What have you tried so far?"
        )
        self.level = level
        self.history = messages + [("model", reply)]
        if display_text:
            self.log.append(("user", display_text))
        self.log.append(("assistant", reply))

        m = _clean(turn.misconception, 60)
        if m and len(self.misconceptions) < 20:
            self.misconceptions.append(m)
        t = _clean(turn.topic, 40)
        if t:
            self.topic = t
        for u in turn.node_updates:
            node, status = _nid(u.node_id), u.status.strip().lower()
            if node in self.status and status in ("green", "red"):
                self.status[node] = status
        return turn

    def start(self) -> TutorTurn:
        self.build_graph()
        return self._turn("I'm stuck on this problem. Please help me.", None, self.level)

    def say(self, message: str) -> TutorTurn:
        return self._turn(message, message[: config.MAX_MESSAGE_CHARS], self.level)

    def next_hint(self) -> TutorTurn:
        new_level = min(self.level + 1, self.MAX_HINT_LEVEL) if self.level < 4 else 4
        return self._turn(
            "I'm still stuck. Please give me a stronger hint.",
            f"💡 Hint requested (level {new_level})",
            new_level,
        )

    def unlock_solution(self) -> TutorTurn:
        return self._turn(
            "I give up. Please show me the full solution.",
            "🔓 Solution requested",
            4,
        )

    # ---------- trap twin ----------
    def make_twin(self) -> "Session":
        twin = self._ask(
            TwinProblem,
            f"Original problem the student solved:\n{self.problem}",
            TWIN_PROMPT,
            config.MAX_OUTPUT_TOKENS_SOLUTION,
        )
        return Session(
            twin.problem,
            self.language,
            trap_note=_clean(twin.trap, 400),
            round_no=self.round_no + 1,
            calls=self.calls,
        )