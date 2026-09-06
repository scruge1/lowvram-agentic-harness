"""Offline stand-in for `research_ground ground`; emits its normal receipt shape."""

import hashlib
import json

sources = {
    "https://a.example/evidence": "The example uses independently checked evidence.",
    "https://b.example/evidence": "Independent evidence is checked by the example.",
}

print(
    json.dumps(
        {
            "question": "What does the example establish?",
            "verdict": "grounded",
            "source_records": [
                {
                    "url": url,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "chars": len(text),
                }
                for url, text in sources.items()
            ],
            "consensus": [
                {
                    "claim": "The example uses independently checked evidence.",
                    "n_sources": 2,
                    "citations": [
                        "https://a.example/evidence",
                        "https://b.example/evidence",
                    ],
                    "evidence": [
                        {
                            "url": "https://a.example/evidence",
                            "quote": sources["https://a.example/evidence"],
                        },
                        {
                            "url": "https://b.example/evidence",
                            "quote": sources["https://b.example/evidence"],
                        },
                    ],
                }
            ],
        }
    )
)
