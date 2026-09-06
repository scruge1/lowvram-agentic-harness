"""A worker that demonstrates correction after independent rejection."""

import os
from pathlib import Path


attempt = int(os.environ["ENFORCEMENT_ATTEMPT"])
feedback = Path(os.environ["ENFORCEMENT_FEEDBACK_FILE"]).read_text(encoding="utf-8")
research = Path(os.environ["ENFORCEMENT_RESEARCH_RECEIPT"])
output = Path("artifacts/result.txt")
output.parent.mkdir(exist_ok=True)

if attempt == 1:
    output.write_text("unchecked first attempt\n", encoding="utf-8")
elif research.is_file() and "independent verifier rejected" in feedback:
    output.write_text(
        "accepted: admitted research and corrective retry were used\n", encoding="utf-8"
    )
else:
    output.write_text(
        "worker did not receive its enforcement context\n", encoding="utf-8"
    )
