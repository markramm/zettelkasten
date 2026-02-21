"""
cascade-research Web UI - Main Application

Streamlit multi-page app for browsing timeline events, actors, and research.
"""

from pathlib import Path

import streamlit as st

# Page config must be first Streamlit command
st.set_page_config(
    page_title="cascade-research", page_icon="🔍", layout="wide", initial_sidebar_state="expanded"
)

# Import pages
pages_dir = Path(__file__).parent / "pages"

# Define navigation structure
search_page = st.Page(str(pages_dir / "search.py"), title="Search", icon="🔍", default=True)
timeline_page = st.Page(str(pages_dir / "timeline.py"), title="Timeline", icon="📅")
actors_page = st.Page(str(pages_dir / "actors.py"), title="Actors", icon="👤")
entry_page = st.Page(str(pages_dir / "entry.py"), title="Entry Detail", icon="📄")

# Group pages
pg = st.navigation(
    {
        "Explore": [search_page, timeline_page, actors_page],
        "Detail": [entry_page],
    }
)

# Shared sidebar
with st.sidebar:
    st.title("🔍 cascade-research")
    st.caption("Research knowledge base explorer")

    st.divider()

    # Global search
    search_query = st.text_input(
        "Quick Search", key="global_search", placeholder="Search all entries..."
    )

    # KB selector
    from cascade_research.ui.data import get_kb_list

    kbs = get_kb_list()
    kb_options = ["All KBs"] + [kb["name"] for kb in kbs]
    selected_kb = st.selectbox("Knowledge Base", kb_options, key="selected_kb")

    st.divider()

    # Stats
    from cascade_research.ui.data import get_stats

    stats = get_stats()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Entries", f"{stats['total_entries']:,}")
    with col2:
        st.metric("Tags", f"{stats['total_tags']:,}")

# Run selected page
pg.run()
