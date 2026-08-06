from __future__ import annotations

import argparse
from pathlib import Path

from .bundle import (
    BundleRequest,
    UniversalBundleRequest,
    create_bundle,
    create_universal_bundle,
    secret_from_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an AI Workday telemetry bundle"
    )
    parser.add_argument("--universal", action="store_true")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--employee-id")
    parser.add_argument("--employee-name")
    parser.add_argument("--api-endpoint")
    parser.add_argument("--collector-endpoint", required=True)
    parser.add_argument("--default-email-domain", default="local.dev")
    parser.add_argument("--trusted-root-ca-file", type=Path)
    parser.add_argument("--expires-in-days", type=int, default=30)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.universal:
        if not args.api_endpoint:
            parser.error("--api-endpoint is required with --universal")
        request = UniversalBundleRequest(
            project_id=args.project_id,
            api_endpoint=args.api_endpoint,
            collector_endpoint=args.collector_endpoint,
            default_email_domain=args.default_email_domain,
            trusted_root_ca_file=args.trusted_root_ca_file,
        )
        output = create_universal_bundle(
            request=request,
            output_root=args.output_root,
        )
    else:
        if not args.employee_id or not args.employee_name:
            parser.error(
                "--employee-id and --employee-name are required "
                "for a legacy employee bundle"
            )
        request = BundleRequest(
            project_id=args.project_id,
            employee_id=args.employee_id,
            employee_name=args.employee_name,
            collector_endpoint=args.collector_endpoint,
            expires_in_days=args.expires_in_days,
        )
        output = create_bundle(
            request=request,
            secret=secret_from_environment(),
            output_root=args.output_root,
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
