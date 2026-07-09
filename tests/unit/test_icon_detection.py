from wire.agents.extraction.comprehensive_extractor import ComprehensiveExtractor

detect = ComprehensiveExtractor.detect_icon_library


def test_detects_known_icon_libraries():
    assert detect('<i class="fa fa-home"></i>') == "font-awesome"
    assert detect('<span class="material-icons">home</span>') == "material"
    assert detect('<svg data-lucide="home"></svg>') == "lucide"
    assert detect('<i class="bi bi-house"></i>') == "bootstrap-icons"
    assert detect('<i class="ph ph-house"></i>') == "phosphor"
    assert detect('<span class="ri-home-line"></span>') == "remixicon"


def test_falls_back_to_inline_svg_then_unknown():
    assert detect("<div><svg><path/></svg></div>") == "inline-svg"
    assert detect("<div>no icons here</div>") == "unknown"
