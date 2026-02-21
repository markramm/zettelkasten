from __future__ import annotations

import os


class LLMClient:
    """A thin wrapper for pluggable LLM providers.
    Currently supports: 'openai' (via OPENAI_API_KEY) and 'stub' (returns canned responses).
    """

    def __init__(self, provider: str = "stub", api_key: str = "", api_base: str = ""):
        self.provider = provider.lower()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.api_base = api_base or os.getenv("OPENAI_API_BASE", "")
        self._openai = None
        if self.provider == "openai" and self.api_key:
            try:
                import openai
                from openai import OpenAI

                self._openai = OpenAI(api_key=self.api_key, base_url=self.api_base or None)
                self._openai_legacy = openai
                if self.api_base:
                    self._openai_legacy.base_url = self.api_base
                self._openai_legacy.api_key = self.api_key
            except Exception as e:
                print(f"[LLM] OpenAI import failed, falling back to stub: {e}")
                self.provider = "stub"

    def summarize(self, text: str, sentences: int = 3) -> str:
        if self.provider != "openai" or not self._openai:
            # simple heuristic summary (first N sentences)
            parts = [p.strip() for p in text.split(".") if p.strip()]
            return ". ".join(parts[:sentences]) + ("." if parts else "")
        try:
            # Use Chat Completions (gpt-4o-mini or gpt-3.5-turbo compatible)
            msgs = [
                {"role": "system", "content": "Summarize text concisely."},
                {"role": "user", "content": f"Summarize in {sentences} sentences:\n{text}"},
            ]
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini", messages=msgs, temperature=0.2, max_tokens=300
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] summarize error: {e}")
            return ""

    def generate_summary(self, text: str, max_length: int = 280) -> str:
        """Generate a concise summary within the specified character limit."""
        if self.provider != "openai" or not self._openai:
            # simple heuristic: take first words up to limit
            words = text.strip().split()
            summary = ""
            for word in words:
                if len(summary + " " + word) > max_length:
                    break
                summary += " " + word if summary else word
            return summary.strip()

        try:
            msgs = [
                {
                    "role": "system",
                    "content": f"Create a concise summary that captures the key points. Keep it under {max_length} characters.",
                },
                {"role": "user", "content": f"Summarize this text concisely:\n{text}"},
            ]
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                temperature=0.2,
                max_tokens=max_length // 4,  # rough estimate for token limit
            )
            summary = resp.choices[0].message.content.strip()

            # Truncate if it exceeds the limit
            if len(summary) > max_length:
                summary = summary[: max_length - 3] + "..."

            return summary
        except Exception as e:
            print(f"[LLM] generate_summary error: {e}")
            # Fallback to simple truncation
            return text[: max_length - 3] + "..." if len(text) > max_length else text

    def feynman_probe(self, concept: str, explanation: str) -> str:
        """Return either a single-question probe, or 'FEYNMAN_COMPLETE'."""
        if self.provider != "openai" or not self._openai:
            # simple stub: if explanation length > threshold, call it complete
            return (
                "FEYNMAN_COMPLETE"
                if len(explanation.split()) > 40
                else "Can you define the key term more simply?"
            )
        try:
            sys = "You are Kyno, a curious 12-year-old. Ask one simple question to clarify."
            user = f"The user is explaining: {concept}\nTheir explanation: {explanation}"
            inst = "If the explanation is perfectly clear to a 12-year-old, reply exactly 'FEYNMAN_COMPLETE'. Otherwise ask one short question."
            msgs = [
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
                {"role": "assistant", "content": inst},
            ]
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini", messages=msgs, temperature=0.7, max_tokens=120
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] probe error: {e}")
            return "Can you give a concrete example?"

    def refine(self, draft: str) -> str:
        if self.provider != "openai" or not self._openai:
            return draft  # no-op stub
        try:
            msgs = [
                {
                    "role": "system",
                    "content": "Rewrite clearly and concisely, suitable for a permanent Zettelkasten note.",
                },
                {"role": "user", "content": draft},
            ]
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini", messages=msgs, temperature=0.3, max_tokens=400
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] refine error: {e}")
            return draft

    def suggest_metadata(self, text: str) -> dict:
        """Return {'title': str, 'tags': [..], 'summary': str}"""
        if self.provider != "openai" or not self._openai:
            # Heuristic: title = first 6 words capitalized; tags from top keywords
            import collections
            import re

            words = re.findall(r"[A-Za-z]{4,}", text.lower())
            common = [w for w, _ in collections.Counter(words).most_common(5)]
            title = " ".join(text.strip().split()[:6]).strip().title() or "Untitled"
            return {
                "title": title,
                "tags": common[:3],
                "summary": " ".join(text.strip().split()[:24]),
            }
        try:
            msgs = [
                {"role": "system", "content": "Act as an expert Zettelkasten librarian."},
                {
                    "role": "user",
                    "content": f"Given this note text, output JSON with keys title,tags,summary. Text:\n{text}",
                },
            ]
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini", messages=msgs, temperature=0.4, max_tokens=200
            )
            import json

            out = resp.choices[0].message.content.strip()
            data = json.loads(out)
            if "tags" in data and isinstance(data["tags"], str):
                data["tags"] = [t.strip() for t in data["tags"].split(",") if t.strip()]
            return data
        except Exception as e:
            print(f"[LLM] metadata error: {e}")
            return {"title": "Untitled", "tags": [], "summary": text[:200]}
