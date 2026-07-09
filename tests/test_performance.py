import time

from wire.schema.style_mapper import CascadeResolver


def generate_large_document():
    html_blocks = []
    css_rules = []

    # 5,000 nodes, 20 stylesheets logic
    for i in range(100):
        html_blocks.append(f"""
            <div id="container-{i}" class="grid-layout">
                <header class="header highlight">Title {i}</header>
                <article>
                    <p class="text">content paragraph <span class="badge">test</span></p>
                    <ul class="list">
                        <li>1</li><li>2</li><li>3</li><li>4</li><li>5</li>
                    </ul>
                </article>
            </div>
        """)
        css_rules.append(f"""
            #container-{i} {{ background-color: #f{i%10}f{i%10}f{i%10}; padding: 10px; }}
            #container-{i} .header {{ color: #000; font-size: 20px; }}
            #container-{i} ul > li:first-child {{ font-weight: bold; }}
            .highlight {{ color: red; }}
            .badge {{ background: yellow; }}
        """)

    htmlStr = f"<html><head><style>{''.join(css_rules)}</style></head><body>{''.join(html_blocks)}</body></html>"
    return htmlStr


def test_cascade_performance():
    htmlStr = generate_large_document()

    start_time = time.time()
    resolver = CascadeResolver()
    soup, styles_map = resolver.resolve(htmlStr, "")
    duration = time.time() - start_time

    print(f"Performance trace: {len(styles_map)} elements styled in {duration:.4f}s")

    # Linear-stability guard: ~1300 elements must resolve well within a generous
    # bound. The bound is deliberately loose so the test stays green under
    # coverage instrumentation and on slow CI runners — it only catches a
    # pathological (e.g. O(n^2)) regression, not normal timing jitter.
    assert duration < 20.0, f"Cascade resolution too slow: {duration:.2f}s"
