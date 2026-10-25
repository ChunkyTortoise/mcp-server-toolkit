"""Run the packaged gateway from a source checkout.

Same as `mcp-toolkit-gateway` or `python -m mcp_toolkit.gateway`; the app lives
in mcp_toolkit/gateway/app.py.
"""

from mcp_toolkit.gateway import main

if __name__ == "__main__":
    main()
