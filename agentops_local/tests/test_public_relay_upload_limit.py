from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


class PublicRelayUploadLimitTests(unittest.TestCase):
    def test_v4_proxy_allows_500_mb_materials_plus_multipart_overhead(self) -> None:
        config_path = Path(
            os.environ.get(
                "PUBLIC_RELAY_NGINX_PATH",
                Path(__file__).parents[2] / "deploy" / "public-relay" / "nginx" / "smartbrain-ip.conf",
            )
        )
        config = config_path.read_text(encoding="utf-8")
        match = re.search(
            r"location\s+\^~\s+/v4/\s*\{(?P<body>.*?)\n\s*\}",
            config,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "public relay /v4/ location is missing")
        self.assertRegex(
            match.group("body"),
            r"client_max_body_size\s+512m;",
        )


if __name__ == "__main__":
    unittest.main()
