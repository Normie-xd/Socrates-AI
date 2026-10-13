import logging

import streamlit as st

import config
import usage
from llm_client import LLMError
from socrates import InvalidProblem, Session

log = logging.getLogger("socrates.app")

st.set_page_config(page_title="Socrates AI", page_icon="🏛️", layout="wide")
st.markdown(
    "<style>.block-container{padding-top:1.5rem;padding-bottom:1rem;}</style>",
    unsafe_allow_html=True,
)

CHAT_HEIGHT = 520
LEVEL_NAMES = {1: "Diagnose", 2: "Concept", 3: "Approach", 4: "Solution"}
EXAMPLE = (
    "Two Sum: Given an array of integers nums and an integer target, return the "
    "indices of the two numbers that add up to target. Each input has exactly "
    "one solution. Example: nums = [2,7,11,15], target = 9 -> [0,1]."
)


def run(action, *args):
    """Run a model call with a spinner. Returns None (after showing an error) on failure."""
    try:
        with st.spinner("Socrates is thinking..."):
            return action(*args)
    except InvalidProblem as e:
        st.warning(f"🤔 That doesn't look like a solvable problem. {e}")
    except (LLMError, usage.LimitReached) as e:
        st.error(str(e))
    except Exception:  # noqa: BLE001
        log.exception("Unhandled error")
        st.error("Something went wrong. See the terminal for details.")
    return None


def begin(problem: str, language: str):
    session = Session(problem, language)
    if run(session.start) is not None:
        st.session_state.session = session
        st.rerun()


def ladder(level: int) -> str:
    parts = []
    for i, name in LEVEL_NAMES.items():
        icon = "🟢" if i < level else ("🔵" if i == level else "⚪")
        parts.append(f"{icon} **{name}**" if i == level else f"{icon} {name}")
    return "  →  ".join(parts)


def start_screen():
    st.title("🏛️ Socrates AI")
    st.caption(
        "A tutor that never gives you the answer. It maps what you actually "
        "understand, then tests whether you can transfer it."
    )
    problem = st.text_area(
        "Paste a LeetCode / Codeforces problem",
        height=220,
        max_chars=config.MAX_PROBLEM_CHARS,
        placeholder=EXAMPLE,
    )
    language = st.selectbox("Language for the final solution", config.LANGUAGES)
    c1, c2, _ = st.columns([1, 1.4, 5])
    if c1.button("Start", type="primary"):
        if problem.strip():
            begin(problem, language)
        else:
            st.warning("Paste a problem first.")
    if c2.button("Try an example"):
        begin(EXAMPLE, language)
    st.caption("Free-tier note: don't paste private or confidential material.")


def main_screen(session: Session):
    # Handle chat input first so everything below renders fresh state.
    prompt = st.chat_input(
        "Explain your thinking, or paste your code...",
        max_chars=config.MAX_MESSAGE_CHARS,
    )
    if prompt and prompt.strip():
        if run(session.say, prompt) is not None:
            st.rerun()

    st.title("🏛️ Socrates AI")
    if session.round_no > 1:
        st.info(f"🪤 Trap Twin round {session.round_no}: looks familiar, but is it?")

    col_chat, col_map = st.columns([3, 2], gap="large")

    with col_chat:
        with st.expander("📄 Problem", expanded=True):
            st.markdown(session.problem)
        chat_box = st.container(height=CHAT_HEIGHT, border=True)
        with chat_box:  # fixed height + chat messages = scrolls and sticks to the bottom
            for role, text in session.log:
                with st.chat_message(role, avatar="🏛️" if role == "assistant" else None):
                    st.markdown(text)

    with col_map:
        st.subheader("Understanding Map")
        st.graphviz_chart(session.map_dot(), width="stretch")
        st.caption("🟩 in your own words   🟥 misconception   ⬜ not yet explored")

        green, total = session.progress()
        st.progress(green / total if total else 0.0, text=f"Understood {green}/{total} concepts")
        st.markdown(ladder(session.level))

        b1, b2 = st.columns(2)
        if b1.button(
            "💡 Stronger hint",
            width="stretch",
            disabled=session.level >= session.MAX_HINT_LEVEL,
        ):
            if run(session.next_hint) is not None:
                st.rerun()
        if b2.button("🔓 Show solution", width="stretch", disabled=session.level == 4):
            if run(session.unlock_solution) is not None:
                st.rerun()

        if st.button("🪤 I solved it: give me a Trap Twin", width="stretch"):
            twin = run(session.make_twin)
            if twin is not None and run(twin.start) is not None:
                st.session_state.session = twin
                st.rerun()

        if session.misconceptions:
            st.markdown("**Misconceptions spotted**")
            for m in dict.fromkeys(session.misconceptions):
                st.text(f"• {m}")  # plain text: never render model output as markdown here

        if st.button("↩️ New problem", width="stretch"):
            del st.session_state["session"]
            st.rerun()
        st.caption(f"AI calls this session: {session.calls}/{config.MAX_CALLS_PER_SESSION}")


if "session" not in st.session_state:
    start_screen()
else:
    main_screen(st.session_state.session)