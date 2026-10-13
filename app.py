import logging
import streamlit as st
import config
import usage
from llm_client import LLMError
from socrates import InvalidProblem, Session

log = logging.getLogger("socrates.app")

st.set_page_config(
    page_title="Socrates AI | Socratic Algorithmic Tutor",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Glassmorphism & High-Contrast Modern Theme CSS
st.markdown(
    """
    <style>
    /* Main Container Padding */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    /* Header & Hero Gradient */
    .hero-title {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #6366F1 0%, #A855F7 50%, #EC4899 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    
    /* Metric Cards */
    .metric-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    
    /* Badge styling */
    .level-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
        background-color: #6366F1;
        color: white;
    }
    
    /* Custom Streamlit Buttons styling */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-1px);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CHAT_HEIGHT = 540
LEVEL_NAMES = {1: "Diagnose", 2: "Concept", 3: "Approach", 4: "Solution"}
EXAMPLE = (
    "Two Sum: Given an array of integers nums and an integer target, return "
    "indices of the two numbers such that they add up to target.\n"
    "Example: nums = [2,7,11,15], target = 9 -> Output: [0,1]."
)

# ... [Keep your run(), begin(), ladder() functions intact] ...

def start_screen():
    st.markdown('<h1 class="hero-title">🏛️ Socrates AI</h1>', unsafe_allow_html=True)
    st.markdown(
        "**Master Competitive Programming through Socratic Dialogue & Dynamic Mind Mapping.**  \n"
        "_Socrates maps your true conceptual understanding without spoiling answers outright._"
    )
    st.divider()

    col_in, col_info = st.columns([3, 2], gap="large")
    
    with col_in:
        problem = st.text_area(
            "📋 Paste LeetCode / Codeforces Problem Statement",
            height=240,
            max_chars=config.MAX_PROBLEM_CHARS,
            placeholder=EXAMPLE,
            help="Paste the full problem text including constraints and sample inputs."
        )
        language = st.selectbox("🎯 Target Language for Level 4 Solution", config.LANGUAGES)
        
        b1, b2 = st.columns([1, 1.5])
        if b1.button("🚀 Start Session", type="primary", use_container_width=True):
            if problem.strip():
                begin(problem, language)
            else:
                st.warning("Please paste a problem statement first.")
        if b2.button("✨ Load Example (Two Sum)", use_container_width=True):
            begin(EXAMPLE, language)

    with col_info:
        st.markdown("### 💡 How Socrates Works")
        st.info(
            "1. **No Direct Code Spoilers**: Socrates asks targeted questions to isolate flaws.\n"
            "2. **Real-time Map**: Visualizes concepts as you explain them in your own words.\n"
            "3. **Trap Twins**: Unlocks conceptual transfer tests once solved."
        )

def main_screen(session: Session):
    # Chat handling
    prompt = st.chat_input("Explain your thinking, approach, or paste code...")
    if prompt and prompt.strip():
        if run(session.say, prompt) is not None:
            st.rerun()

    # Top Header Banner
    c_title, c_meta = st.columns([3, 1])
    with c_title:
        st.markdown('<h2 class="hero-title">🏛️ Socrates AI Session</h2>', unsafe_allow_html=True)
    with c_meta:
        st.markdown(f"<div style='text-align:right;'><span class='level-badge'>Level {session.level}: {LEVEL_NAMES[session.level]}</span></div>", unsafe_allow_html=True)

    if session.round_no > 1:
        st.warning(f"🪤 **Trap Twin Round {session.round_no}**: A similar problem with a structural twist.")

    st.divider()
    col_chat, col_map = st.columns([3, 2], gap="large")

    with col_chat:
        with st.expander("📄 **Problem Statement**", expanded=False):
            st.markdown(session.problem)
            
        chat_box = st.container(height=CHAT_HEIGHT, border=True)
        with chat_box:
            for role, text in session.log:
                avatar = "🏛️" if role == "assistant" else "🧑‍💻"
                with st.chat_message(role, avatar=avatar):
                    st.markdown(text)

    with col_map:
        st.subheader("🧠 Concept Graph")
        st.graphviz_chart(session.map_dot(), use_container_width=True)
        
        green, total = session.progress()
        st.progress(green / total if total else 0.0, text=f"Mastered {green}/{total} Core Concepts")
        st.markdown(ladder(session.level))

        st.markdown("---")
        st.markdown("### 🛠️ Actions")
        
        b1, b2 = st.columns(2)
        if b1.button("💡 Stronger Hint", use_container_width=True, disabled=session.level >= session.MAX_HINT_LEVEL):
            if run(session.next_hint) is not None:
                st.rerun()
        if b2.button("🔓 Show Solution", use_container_width=True, disabled=session.level == 4):
            if run(session.unlock_solution) is not None:
                st.rerun()

        if st.button("🪤 Request Trap Twin (Transfer Test)", type="primary", use_container_width=True):
            twin = run(session.make_twin)
            if twin is not None and run(twin.start) is not None:
                st.session_state.session = twin
                st.rerun()

        if session.misconceptions:
            with st.expander("⚠️ Detected Misconceptions", expanded=True):
                for m in dict.fromkeys(session.misconceptions):
                    st.error(f"• {m}")

        if st.button("🔄 Start New Problem", use_container_width=True):
            del st.session_state["session"]
            st.rerun()