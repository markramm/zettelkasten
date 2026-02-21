"""
Entry Detail Page - View full entry content.
"""

import streamlit as st

from cascade_research.ui.data import get_entry, search

st.header("📄 Entry Detail")

# Get selected entry from session state
entry_id = st.session_state.get("selected_entry_id")
entry_kb = st.session_state.get("selected_entry_kb")

if not entry_id:
    st.info("No entry selected. Use Search or Timeline to find an entry.")

    # Quick search
    quick_id = st.text_input("Or enter an entry ID directly:")
    if quick_id:
        entry_id = quick_id

if entry_id:
    with st.spinner("Loading entry..."):
        entry = get_entry(entry_id, entry_kb)

    if not entry:
        st.error(f"Entry '{entry_id}' not found.")
    else:
        # Entry header
        st.title(entry["title"])

        # Metadata badges
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"**KB:** {entry['kb_name']}")
        with col2:
            st.markdown(f"**Type:** {entry['entry_type']}")
        with col3:
            if entry.get("date"):
                st.markdown(f"**Date:** {entry['date']}")
        with col4:
            if entry.get("importance"):
                st.markdown(f"**Importance:** {entry['importance']}/10")

        st.divider()

        # Tags
        if entry.get("tags"):
            st.markdown("**Tags:** " + " ".join([f"`{tag}`" for tag in entry["tags"]]))

        # Actors
        if entry.get("actors"):
            st.markdown("**Actors:** " + ", ".join(entry["actors"]))

        st.divider()

        # Body content
        st.markdown("### Content")
        if entry.get("body"):
            st.markdown(entry["body"])
        else:
            st.info("No content available.")

        # Sources
        if entry.get("sources"):
            st.divider()
            st.markdown("### Sources")
            for i, source in enumerate(entry["sources"], 1):
                if isinstance(source, dict):
                    title = source.get("title", f"Source {i}")
                    url = source.get("url", "")
                    outlet = source.get("outlet", "")
                    if url:
                        st.markdown(f"{i}. [{title}]({url}) - {outlet}")
                    else:
                        st.markdown(f"{i}. {title} - {outlet}")
                else:
                    st.markdown(f"{i}. {source}")

        # Links
        col1, col2 = st.columns(2)

        with col1:
            if entry.get("outlinks"):
                st.divider()
                st.markdown("### Outgoing Links")
                for link in entry["outlinks"]:
                    target_id = link.get("target_id", link.get("to", ""))
                    relation = link.get("relation", link.get("type", "related"))
                    if st.button(f"→ {target_id} ({relation})", key=f"out_{target_id}"):
                        st.session_state.selected_entry_id = target_id
                        st.session_state.selected_entry_kb = None
                        st.rerun()

        with col2:
            if entry.get("backlinks"):
                st.divider()
                st.markdown("### Backlinks")
                for link in entry["backlinks"]:
                    source_id = link.get("source_id", "")
                    relation = link.get("relation", "links to")
                    if st.button(f"← {source_id} ({relation})", key=f"back_{source_id}"):
                        st.session_state.selected_entry_id = source_id
                        st.session_state.selected_entry_kb = None
                        st.rerun()

        # Related entries
        st.divider()
        st.markdown("### Related Entries")

        # Search for related entries using title keywords
        title_words = entry["title"].split()[:3]
        if title_words:
            related_query = " ".join(title_words)
            related = search(related_query, limit=5)
            related = [r for r in related if r["id"] != entry_id][:4]

            if related:
                for r in related:
                    if st.button(f"📄 {r['title']}", key=f"related_{r['id']}"):
                        st.session_state.selected_entry_id = r["id"]
                        st.session_state.selected_entry_kb = r["kb_name"]
                        st.rerun()
            else:
                st.info("No related entries found.")

        # File path
        st.divider()
        st.caption(f"File: `{entry.get('file_path', 'unknown')}`")
