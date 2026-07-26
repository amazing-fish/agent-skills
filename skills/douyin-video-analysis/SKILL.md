---
name: douyin-video-analysis
description: Use when the user gives a Douyin video link or share text and asks to parse or crawl the video, extract copy or transcript, use key frames or screenshots, interpret the content deeply, or produce a source-grounded research report.
---

# 抖音视频分析

## Overview

Turn a Douyin video link into an evidence-backed research report. Prefer parsed page copy, captions, local/free transcription, and key frames over unsupported inference.

## Workflow

1. **Resolve the input**
   - Extract the first URL from share text.
   - Record the original URL, resolved URL, redirect chain, status code, and crawl method.
   - If a compatible parser exists in the active workspace, prefer its documented CLI over ad hoc scraping. This Skill does not bundle a parser runtime. For a workspace that provides the `douyin_analyzer` package, a compatible example is:
     `python -m douyin_analyzer.cli analyze "<share text or URL>" --out outputs/<run-id> --stt-backend auto`

2. **Collect evidence**
   - Extract page title, author, description, hashtags, captions, and video/media URLs.
   - If HTTP parsing fails, use browser rendering/network capture and save diagnostics.
   - Download media only when the source URL is accessible and allowed by the current session constraints.
   - Use free/local speech-to-text first: page captions, then `faster-whisper`, then `FunASR`; do not use paid STT unless the user explicitly asks.
   - Extract 3-7 key frames across the video or around uncertain transcript sections.

3. **Separate evidence from interpretation**
   - Treat transcript text, page metadata, frames, and network diagnostics as evidence.
   - Mark low-confidence ASR, missing captions, blocked pages, or inferred claims.
   - Never invent exact quotes, figures, interactions, claims, or visual details not present in evidence.

4. **Analyze deeply**
   - Identify the video's thesis, argument structure, assumptions, examples, and implied framework.
   - Compare page copy with transcript and frames; flag mismatches.
   - For technical, financial, or trading videos, distinguish education, strategy rules, unverifiable claims, and risk warnings.
   - Use key frames to adjudicate ambiguous transcript passages, especially charts, slides, formulas, or UI demonstrations.

5. **Write the report**
   - Use the structure in `references/report-framework.md`.
   - Make the Markdown report a finished learning/research report, not a transcript dump or artifact index.
   - Use transcript and frames as evidence, but do not paste the full transcript or intermediate artifact paths into the main report unless the user explicitly asks.
   - Explain terms, techniques, principles, what each technique is used for, validation boundaries, and what the viewer can learn.
   - Keep raw transcript, media paths, diagnostics, and key frame paths in machine-readable artifacts such as JSON or a separate appendix when available.

## Failure Handling

- If crawling fails, do not stop at "failed". Save and analyze the page structure: HTML snapshot, scripts summary, HTTP metadata, browser screenshot, and network log.
- If media downloads fail but metadata exists, produce a partial report and list the missing evidence.
- If transcription is unavailable, explain the missing free backend briefly and still analyze page copy and frames.

## Quality Bar

- A report is not complete until it reads like a useful study note: source summary, content structure, terminology, techniques/principles, learning path, uncertainties, and validation boundaries.
- Raw transcript and intermediate artifact paths are evidence storage, not the body of the Markdown report.
- Re-run the narrowest relevant command before claiming the result is complete.
- Keep the report useful for a reader who will not inspect the raw video.
