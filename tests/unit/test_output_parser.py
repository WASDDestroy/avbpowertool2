"""Contract tests for output_parser against known avbtool output fixtures."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.infrastructure.avbtool.output_parser import parse_info_image

FIXTURES = Path(__file__).parent.parent / "fixtures" / "avbtool_output"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseHashDescriptor:
    def test_header_fields(self) -> None:
        result = parse_info_image(_load("hash_descriptor.txt"))
        h = result["header"]
        assert h["Footer version"] == "1.0"
        assert h["Algorithm"] == "NONE"
        assert h["Rollback Index"] == "0"
        assert h["Flags"] == "0"
        assert "cd2c1e5e" in h["Public key (sha1)"]

    def test_descriptor_block(self) -> None:
        result = parse_info_image(_load("hash_descriptor.txt"))
        descs = result["descriptors"]
        assert len(descs) == 1
        assert descs[0]["type"] == "Hash"
        fields = descs[0]["fields"]
        assert fields["Partition Name"] == "boot"
        assert fields["Hash Algorithm"] == "sha256"
        assert "67108864" in fields["Image Size"]

    def test_no_props(self) -> None:
        result = parse_info_image(_load("hash_descriptor.txt"))
        assert result["props"] == []


class TestParseHashtreeDescriptor:
    def test_descriptor_type(self) -> None:
        result = parse_info_image(_load("hashtree_descriptor.txt"))
        descs = result["descriptors"]
        assert len(descs) == 1
        assert descs[0]["type"] == "Hashtree"

    def test_fields(self) -> None:
        result = parse_info_image(_load("hashtree_descriptor.txt"))
        fields = result["descriptors"][0]["fields"]
        assert fields["Partition Name"] == "system"
        assert fields["Data Block Size"] == "4096 bytes"
        assert fields["FEC num roots"] == "2"


class TestParseVbmetaNoDescriptors:
    def test_header_algorithm(self) -> None:
        result = parse_info_image(_load("vbmeta_no_descriptors.txt"))
        assert result["header"]["Algorithm"] == "SHA256_RSA4096"

    def test_no_descriptors(self) -> None:
        result = parse_info_image(_load("vbmeta_no_descriptors.txt"))
        assert result["descriptors"] == []


class TestParseVbmetaWithChain:
    def test_two_chain_descriptors(self) -> None:
        result = parse_info_image(_load("vbmeta_with_chain.txt"))
        descs = result["descriptors"]
        assert len(descs) == 2
        assert all(d["type"] == "Chain Partition" for d in descs)

    def test_chain_fields(self) -> None:
        result = parse_info_image(_load("vbmeta_with_chain.txt"))
        f0 = result["descriptors"][0]["fields"]
        assert f0["Partition Name"] == "vbmeta_system"
        assert f0["Rollback Index Location"] == "1"
        f1 = result["descriptors"][1]["fields"]
        assert f1["Partition Name"] == "vbmeta_vendor"
        assert f1["Rollback Index Location"] == "2"


class TestParseHashWithProps:
    def test_props_extracted(self) -> None:
        result = parse_info_image(_load("hash_with_props.txt"))
        props = result["props"]
        assert len(props) == 2
        assert props[0] == ("com.android.build.boot.os_version", "14")
        assert props[1] == ("com.android.build.boot.security_patch", "2024-01-05")

    def test_header_algorithm(self) -> None:
        result = parse_info_image(_load("hash_with_props.txt"))
        assert result["header"]["Algorithm"] == "SHA256_RSA4096"
        assert result["header"]["Rollback Index"] == "3"


class TestParseEdgeCases:
    def test_empty_string(self) -> None:
        result = parse_info_image("")
        assert result["header"] == {}
        assert result["descriptors"] == []
        assert result["props"] == []

    def test_blank_lines_ignored(self) -> None:
        text = "Algorithm:                SHA1\n\n\nRollback Index:           5\n"
        result = parse_info_image(text)
        assert result["header"] == {"Algorithm": "SHA1", "Rollback Index": "5"}

    def test_single_header_field(self) -> None:
        text = "Footer version:           1.0\n"
        result = parse_info_image(text)
        assert result["header"]["Footer version"] == "1.0"
        assert result["descriptors"] == []
