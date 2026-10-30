"""Windows bundle entry point; normal startup uses the original application."""

import os

from main import main


if __name__ == "__main__":
    if os.environ.get("WAYBILL_SELF_CHECK"):
        from runtime_check import run
        raise SystemExit(run())
    raise SystemExit(main())
