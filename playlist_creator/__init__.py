"""Suggest playlists for a YouTube channel's videos.

Pipeline: fetch -> transcribe -> summarize (OpenRouter) -> cluster (embeddings) ->
propose playlists -> score fit with Jev (TypeSafe) -> report.
"""
