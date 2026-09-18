# XM3600 official-source validation

This gate validates the adapter against the live official Crossmodal-3600
metadata/caption feed instead of only synthetic fixtures.

It downloads the small `image_ids.txt` metadata file and streams only the first
five records from the official `web_captions.jsonl` feed. It does not download
the 302 MB image archive.

The official web viewer represents each record with `imageId`, `imageLocale`,
and `captions`, where captions are a list of
`[language, [caption, ...]]` pairs. The gate verifies those image IDs occur in
the official 3600-image ID inventory, normalizes captions through the adapter,
and confirms broad multilingual coverage including English, German, and Thai.

This is source-format/acquisition qualification, not model-performance evidence.
