from __future__ import annotations

import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "explain-diff-for-human-review"
THEME_PATH = SKILL_DIR / "assets" / "report-theme.css"


def _theme_tokens(css: str, selector_pattern: str) -> dict[str, str]:
    match = re.search(selector_pattern, css, flags=re.DOTALL)
    if match is None:
        raise AssertionError(f"missing theme block: {selector_pattern}")
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", match.group(1)))


def _relative_luminance(color: str) -> float:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise AssertionError(f"contrast token must use six-digit hex: {color}")
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


class ReportThemePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = THEME_PATH.read_text(encoding="utf-8")
        cls.skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def test_skill_requires_the_bundled_theme_to_be_inlined(self):
        self.assertIn("assets/report-theme.css", self.skill)
        self.assertIn("内联到 HTML 的 `<style>`", self.skill)
        self.assertIn("prefers-color-scheme: dark", self.skill)
        self.assertIn("桌面和移动端宽度", self.skill)

    def test_light_dark_and_print_themes_define_the_same_semantic_tokens(self):
        light = _theme_tokens(self.css, r":root\s*\{([^}]*)\}")
        dark = _theme_tokens(
            self.css,
            r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}",
        )
        print_theme = _theme_tokens(
            self.css,
            r"@media\s+print\s*\{\s*:root\s*\{([^}]*)\}",
        )
        required = {
            "--color-canvas",
            "--color-surface",
            "--color-surface-muted",
            "--color-text",
            "--color-text-muted",
            "--color-border",
            "--color-link",
            "--color-code-bg",
            "--color-code-text",
            "--color-success",
            "--color-success-bg",
            "--color-warning",
            "--color-warning-bg",
            "--color-danger",
            "--color-danger-bg",
            "--color-focus",
        }
        self.assertTrue(required.issubset(light))
        self.assertEqual(set(light), set(dark))
        self.assertEqual(set(light), set(print_theme))

    def test_theme_covers_report_components_responsiveness_focus_and_print(self):
        for selector_or_policy in (
            "color-scheme: light dark",
            ".report-header",
            ".report-nav",
            "a:focus-visible",
            "summary:focus-visible",
            "pre",
            "table",
            ".finding--danger",
            ".finding--warning",
            ".verification--passed",
            "@media (max-width: 760px)",
            "@media print",
        ):
            with self.subTest(selector_or_policy=selector_or_policy):
                self.assertIn(selector_or_policy, self.css)

        self.assertNotIn("@import", self.css)
        self.assertNotIn("url(", self.css)
        non_token_lines = "\n".join(
            line for line in self.css.splitlines() if not re.search(r"--[\w-]+\s*:", line)
        )
        self.assertNotRegex(non_token_lines, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")

    def test_theme_token_pairs_meet_contrast_targets(self):
        themes = {
            "light": _theme_tokens(self.css, r":root\s*\{([^}]*)\}"),
            "dark": _theme_tokens(
                self.css,
                r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}",
            ),
            "print": _theme_tokens(
                self.css,
                r"@media\s+print\s*\{\s*:root\s*\{([^}]*)\}",
            ),
        }
        pairs = (
            ("--color-text", "--color-surface", 4.5),
            ("--color-text-muted", "--color-surface", 4.5),
            ("--color-link", "--color-surface", 4.5),
            ("--color-link-visited", "--color-surface", 4.5),
            ("--color-code-text", "--color-code-bg", 4.5),
            ("--color-success", "--color-success-bg", 4.5),
            ("--color-warning", "--color-warning-bg", 4.5),
            ("--color-danger", "--color-danger-bg", 4.5),
            ("--color-info", "--color-info-bg", 4.5),
            ("--color-focus", "--color-surface", 3.0),
        )
        for theme_name, tokens in themes.items():
            for foreground, background, minimum in pairs:
                with self.subTest(
                    theme=theme_name,
                    foreground=foreground,
                    background=background,
                ):
                    self.assertGreaterEqual(
                        _contrast_ratio(tokens[foreground], tokens[background]),
                        minimum,
                    )


if __name__ == "__main__":
    unittest.main()
