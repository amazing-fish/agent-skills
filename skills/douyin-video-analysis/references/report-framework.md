# 抖音视频分析报告框架

Use this structure for final Markdown reports. The report is for learning and research, not for dumping the raw transcript or listing every intermediate artifact.

## 1. Source Summary

- Video title
- Author/channel
- Original and resolved URL
- Evidence basis: page copy, free/local transcription, key frames, browser diagnostics
- Collection caveat only when it affects interpretation

Do not include a long artifact path list in the main report. Keep those paths in JSON or a separate appendix unless the user asks.

## 2. Core Conclusion

Explain the video thesis in 3-6 bullets:

- What the speaker is teaching
- Whether it is a process, signal, narrative, or sales pitch
- What problem the framework tries to solve
- What the viewer should and should not take away

## 3. Content Structure

Break the video into learning blocks. Example for trading videos:

- Strategy development goal
- Market/flow model
- Indicator or data inputs
- Confirmation sequence
- Risk and invalidation discussion

## 4. Terminology

Create a term table:

| Term | Meaning in this video | Learning note |
|---|---|---|
| Delta/Data | order-flow net difference | verify software calculation before use |

Include domain terms, ambiguous ASR terms, tools, indicators, and jargon.

## 5. Techniques And Principles

For each technique, explain:

- What it is
- What it is used for
- Why it might work
- What evidence is required
- What can make it fail

## 6. Learning Path

Turn the video into concrete study steps and review questions.

## 7. Validation Boundaries

List every important uncertainty with the evidence needed to resolve it. For trading/investment videos, include:

- Required data inputs and whether they are visible
- Missing thresholds, sample size, backtest, or market regime evidence
- Risk management assumptions
- Invalidation conditions
- Clear note: not financial advice
