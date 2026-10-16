"""Tests for the plugin manifest model and its validator."""

from __future__ import annotations

from avbpowertool.domain.plugin import PluginManifest
from avbpowertool.domain.validation import validate_plugin_manifest
from avbpowertool.infrastructure.persistence.plugin_repository import (
    parse_plugin_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _xml(
    *,
    plugin_id: str | None = "demo",
    entry: str | None = "run.cmd",
    names: tuple[tuple[str, str], ...] | None = (("en", "Demo"),),
    descriptions: tuple[tuple[str, str], ...] = (),
    schema_version: str | None = "1",
) -> bytes:
    """Build a manifest document; ``None`` omits the element/attribute."""
    attrs = "" if schema_version is None else f' schema_version="{schema_version}"'
    body = ""
    if plugin_id is not None:
        body += f"<id>{plugin_id}</id>"
    if entry is not None:
        body += f"<entry>{entry}</entry>"
    if names is not None:
        body += "<names>"
        body += "".join(f'<name lang="{lang}">{text}</name>' for lang, text in names)
        body += "</names>"
    body += "".join(
        f'<description lang="{lang}">{text}</description>' for lang, text in descriptions
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f"<avbpowertool_plugin{attrs}>{body}</avbpowertool_plugin>"
    ).encode("utf-8")


def _codes(issues: list) -> list[str]:
    return [issue.error_code for issue in issues]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsePluginManifest:
    def test_parses_a_valid_manifest(self) -> None:
        manifest, issues = parse_plugin_manifest(_xml())

        assert issues == []
        assert manifest == PluginManifest(
            plugin_id="demo", entry="run.cmd", names=(("en", "Demo"),)
        )

    def test_parses_the_shipped_manifest_layout(self) -> None:
        """Same shape as plugins/testkey_config_gen/avbpowertool_plugin_config.xml."""
        manifest, issues = parse_plugin_manifest(
            _xml(
                plugin_id="testkey_config_gen",
                entry="make-testkey-config.cmd",
                names=(("en", "Test-key config generator"), ("zh", "测试密钥配置生成")),
                descriptions=(("zh", "按旗标表生成配置"), ("en", "Generate a config")),
            )
        )

        assert issues == []
        assert manifest.plugin_id == "testkey_config_gen"
        assert manifest.entry == "make-testkey-config.cmd"
        assert manifest.names == (
            ("en", "Test-key config generator"),
            ("zh", "测试密钥配置生成"),
        )
        assert manifest.descriptions == (("zh", "按旗标表生成配置"), ("en", "Generate a config"))
        assert manifest.schema_version == 1

    def test_text_is_stripped(self) -> None:
        manifest, issues = parse_plugin_manifest(
            _xml(plugin_id="  demo  ", entry="  run.cmd  ", names=((" en ", "  Demo  "),))
        )

        assert issues == []
        assert manifest.plugin_id == "demo"
        assert manifest.entry == "run.cmd"
        assert manifest.names == (("en", "Demo"),)

    def test_missing_id_is_reported(self) -> None:
        manifest, issues = parse_plugin_manifest(_xml(plugin_id=None))

        assert _codes(issues) == ["plugin.manifest_invalid"]
        assert "id is empty" in issues[0].message
        assert manifest.plugin_id == ""

    def test_invalid_id_is_reported(self) -> None:
        for bad_id in ("a/b", "a\\b", "..", ".", "demo plugin", "demo:1"):
            _manifest, issues = parse_plugin_manifest(_xml(plugin_id=bad_id))
            assert _codes(issues) == ["plugin.id_invalid"], bad_id

    def test_id_allows_letters_digits_underscore_dash_dot(self) -> None:
        _manifest, issues = parse_plugin_manifest(_xml(plugin_id="My.Plugin-2_x"))

        assert issues == []

    def test_empty_entry_is_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(_xml(entry="   "))

        assert _codes(issues) == ["plugin.entry_missing"]

    def test_entry_with_separator_is_reported(self) -> None:
        for bad_entry in ("bin/run.cmd", "bin\\run.cmd", ".", ".."):
            _manifest, issues = parse_plugin_manifest(_xml(entry=bad_entry))
            assert _codes(issues) == ["plugin.entry_invalid"], bad_entry

    def test_no_names_is_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(_xml(names=None))

        assert _codes(issues) == ["plugin.manifest_invalid"]
        assert "no names" in issues[0].message

    def test_unknown_schema_version_is_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(_xml(schema_version="2"))

        assert _codes(issues) == ["plugin.manifest_invalid"]
        assert "schema_version" in issues[0].message

    def test_non_numeric_schema_version_is_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(_xml(schema_version="one"))

        assert _codes(issues) == ["plugin.manifest_invalid"]

    def test_missing_schema_version_attribute_means_current(self) -> None:
        manifest, issues = parse_plugin_manifest(_xml(schema_version=None))

        assert issues == []
        assert manifest.schema_version == 1

    def test_malformed_xml_is_reported_not_raised(self) -> None:
        manifest, issues = parse_plugin_manifest(b"<avbpowertool_plugin><id>demo")

        assert _codes(issues) == ["plugin.manifest_invalid"]
        assert manifest == PluginManifest(plugin_id="", entry="")

    def test_unexpected_root_element_is_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(b"<plugin><id>demo</id></plugin>")

        assert _codes(issues) == ["plugin.manifest_invalid"]
        assert "root element" in issues[0].message

    def test_multiple_problems_are_all_reported(self) -> None:
        _manifest, issues = parse_plugin_manifest(
            _xml(plugin_id="..", entry="a/b", names=None, schema_version="9")
        )

        assert _codes(issues) == [
            "plugin.manifest_invalid",  # schema version
            "plugin.id_invalid",
            "plugin.entry_invalid",
            "plugin.manifest_invalid",  # no names
        ]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestValidatePluginManifest:
    def test_valid_manifest_has_no_issues(self) -> None:
        issues = validate_plugin_manifest(
            PluginManifest(plugin_id="demo", entry="run.py", names=(("en", "Demo"),))
        )

        assert issues == []

    def test_never_raises_and_returns_issues(self) -> None:
        issues = validate_plugin_manifest(PluginManifest(plugin_id="", entry="", schema_version=3))

        assert _codes(issues) == [
            "plugin.manifest_invalid",
            "plugin.manifest_invalid",
            "plugin.entry_missing",
            "plugin.manifest_invalid",
        ]


# ---------------------------------------------------------------------------
# Localized lookup
# ---------------------------------------------------------------------------


class TestNameResolution:
    NAMES = (
        ("en", "English name"),
        ("zh", "中文名"),
        ("zh_CN", "简体名"),
        ("fr", "Nom français"),
    )

    def test_exact_language_match(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd", names=self.NAMES)

        assert manifest.name_for("zh") == "中文名"
        assert manifest.name_for("zh_CN") == "简体名"
        assert manifest.name_for("fr") == "Nom français"

    def test_language_match_is_case_insensitive(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd", names=self.NAMES)

        assert manifest.name_for("ZH_cn") == "简体名"
        assert manifest.name_for("EN") == "English name"

    def test_regional_code_falls_back_to_primary_subtag(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd", names=self.NAMES)

        # zh_TW is not declared; zh is.
        assert manifest.name_for("zh_TW") == "中文名"

    def test_unknown_language_falls_back_to_english(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd", names=self.NAMES)

        assert manifest.name_for("de") == "English name"

    def test_no_english_falls_back_to_the_first_name(self) -> None:
        manifest = PluginManifest(
            plugin_id="demo", entry="run.cmd", names=(("fr", "Français"), ("zh", "中文"))
        )

        assert manifest.name_for("de") == "Français"

    def test_empty_names_fall_back_to_the_plugin_id(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd")

        assert manifest.name_for("en") == "demo"

    def test_all_empty_names_fall_back_to_the_plugin_id(self) -> None:
        manifest = PluginManifest(
            plugin_id="demo", entry="run.cmd", names=(("en", ""), ("zh", "   "))
        )

        assert manifest.name_for("en") == "demo"
        assert manifest.name_for("zh") == "demo"

    def test_empty_english_does_not_shadow_another_language(self) -> None:
        manifest = PluginManifest(
            plugin_id="demo", entry="run.cmd", names=(("en", ""), ("fr", "Français"))
        )

        assert manifest.name_for("de") == "Français"


class TestDescriptionResolution:
    def test_missing_descriptions_return_empty_string(self) -> None:
        manifest = PluginManifest(plugin_id="demo", entry="run.cmd")

        assert manifest.description_for("en") == ""
        assert manifest.description_for("zh") == ""

    def test_falls_back_like_names_but_never_to_the_id(self) -> None:
        manifest = PluginManifest(
            plugin_id="demo",
            entry="run.cmd",
            descriptions=(("zh", "中文描述"), ("en", "English description")),
        )

        assert manifest.description_for("zh") == "中文描述"
        assert manifest.description_for("zh_CN") == "中文描述"
        assert manifest.description_for("en") == "English description"
        assert manifest.description_for("de") == "English description"

    def test_no_english_uses_the_first_description(self) -> None:
        manifest = PluginManifest(
            plugin_id="demo", entry="run.cmd", descriptions=(("fr", "Description"),)
        )

        assert manifest.description_for("de") == "Description"
