"""
Actors Page - Browse actors by mention count.
"""

import streamlit as st

from cascade_research.ui.data import get_actors, search

st.header("👤 Actors")

# Get actors
actors = get_actors(limit=200)

# Search filter
actor_search = st.text_input("Filter actors", placeholder="Type to filter...")

if actor_search:
    actors = [a for a in actors if actor_search.lower() in a["name"].lower()]

st.divider()
st.subheader(f"Actors: {len(actors)}")

if not actors:
    st.info("No actors found.")
else:
    # Display as grid
    cols_per_row = 3
    for i in range(0, len(actors), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            if i + j < len(actors):
                actor = actors[i + j]
                with col:
                    with st.container():
                        # Actor card
                        st.markdown(f"### {actor['name']}")
                        st.metric("Mentions", actor["mentions"])

                        # Search for this actor
                        if st.button("View Events", key=f"actor_events_{actor['name']}"):
                            st.session_state.global_search = f'"{actor["name"]}"'
                            st.switch_page("pages/search.py")

                        # Check if there's a research entry for this actor
                        if st.button("View Profile", key=f"actor_profile_{actor['name']}"):
                            # Search for actor entry in research-kb
                            results = search(
                                query=actor["name"],
                                kb_name="research-kb",
                                entry_type="actor",
                                limit=1,
                            )
                            if results:
                                st.session_state.selected_entry_id = results[0]["id"]
                                st.session_state.selected_entry_kb = results[0]["kb_name"]
                                st.switch_page("pages/entry.py")
                            else:
                                st.warning(f"No profile found for {actor['name']}")

                    st.divider()
