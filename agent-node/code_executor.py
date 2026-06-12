"""
code_executor.py — Safe Python code execution tool for CrewAI pipeline agents.

Agents call run_code_tool(code) to execute Python inside the container.
Missing packages (pennylane, qiskit, scipy, etc.) are auto-installed on first use.
Matplotlib is forced into Agg (headless) mode so plots don't crash.
"""

import os
import re
import sys
import time
import logging
import tempfile
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Truncate very long outputs so they don't blow up agent context windows
_MAX_STDOUT = 8_000
_MAX_STDERR = 3_000

# Packages that won't be auto-installed (too large / always present)
_SKIP_AUTO_INSTALL = {"os", "sys", "re", "json", "math", "time",
                       "random", "itertools", "functools", "collections",
                       "pathlib", "typing", "dataclasses", "abc", "io",
                       "logging", "subprocess", "threading", "datetime"}

# Map import names → pip package names
_PIP_MAP = {
    "pennylane":   "pennylane",
    "qiskit":      "qiskit",
    "cirq":        "cirq-core",
    "numpy":       "numpy",
    "scipy":       "scipy",
    "matplotlib":  "matplotlib",
    "pandas":      "pandas",
    "sklearn":     "scikit-learn",
    "sympy":       "sympy",
    "networkx":    "networkx",
    "torch":       "torch",
    "jax":         "jax",
    "openpyxl":    "openpyxl",
    "pydantic":    "pydantic",
    "yaml":        "pyyaml",
}


def _auto_install(code: str) -> list[str]:
    """Detect imports in code and pip-install anything missing."""
    imports = re.findall(r"^(?:import|from)\s+([\w]+)", code, re.MULTILINE)
    installed = []
    for name in set(imports):
        if name in _SKIP_AUTO_INSTALL:
            continue
        pkg = _PIP_MAP.get(name)
        if not pkg:
            continue
        try:
            __import__(name)
        except ImportError:
            log.info("Auto-installing %s ...", pkg)
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "-q",
                 "--break-system-packages"],
                capture_output=True, timeout=180,
            )
            if r.returncode == 0:
                installed.append(pkg)
                log.info("Installed %s OK", pkg)
            else:
                log.warning("pip install %s failed: %s",
                            pkg, r.stderr.decode()[:300])
    return installed


def execute_python(code: str, timeout: int = 120) -> dict:
    """
    Run *code* in a subprocess and return a result dict:
      success, stdout, stderr, runtime, returncode, packages_installed
    """
    packages_installed = _auto_install(code)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="/tmp"
    ) as fh:
        fh.write(code)
        tmp = fh.name

    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"          # headless matplotlib — no display needed
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True,
            timeout=timeout, cwd="/tmp", env=env,
        )
        runtime = round(time.time() - t0, 2)

        stdout = r.stdout
        stderr = r.stderr
        if len(stdout) > _MAX_STDOUT:
            stdout = stdout[:_MAX_STDOUT] + f"\n…(truncated {len(r.stdout)-_MAX_STDOUT} chars)"
        if len(stderr) > _MAX_STDERR:
            stderr = stderr[:_MAX_STDERR] + f"\n…(truncated {len(r.stderr)-_MAX_STDERR} chars)"

        return dict(
            success=r.returncode == 0,
            stdout=stdout, stderr=stderr,
            runtime=runtime, returncode=r.returncode,
            packages_installed=packages_installed,
        )

    except subprocess.TimeoutExpired:
        return dict(
            success=False, stdout="",
            stderr=f"Timed out after {timeout}s — simplify the simulation or reduce iterations.",
            runtime=timeout, returncode=-1,
            packages_installed=packages_installed,
        )
    except Exception as exc:
        return dict(
            success=False, stdout="",
            stderr=str(exc),
            runtime=round(time.time() - t0, 2), returncode=-1,
            packages_installed=packages_installed,
        )
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass


# ── CrewAI tool wrapper ───────────────────────────────────────────────────────
try:
    from crewai.tools import tool as _crewai_tool
except ImportError:
    try:
        from crewai_tools import tool as _crewai_tool
    except ImportError:
        def _crewai_tool(name):          # no-op shim for testing outside CrewAI
            def _wrap(fn):
                return fn
            return _wrap


@_crewai_tool("execute_python_code")
def run_code_tool(code: str) -> str:
    """
    Execute Python code and return its output.

    Use this tool to:
    - Run quantum circuit simulations (pennylane, qiskit)
    - Test mathematical / numerical models
    - Verify that generated experiment code actually works
    - Compute and print results rather than guessing them

    Rules for writing the code argument:
    - Include ALL imports at the top of the code string
    - Use print() to emit results — that is what gets returned
    - For plots: call plt.savefig('/tmp/fig.png') and print the path
    - Missing packages (pennylane, qiskit, scipy, matplotlib, …) are
      installed automatically on first use
    - If execution fails, read the error, fix the code, and call again

    Returns: execution output (stdout + any errors).
    """
    log.info("run_code_tool: executing %d-char snippet", len(code))
    result = execute_python(code)

    lines = []
    if result["packages_installed"]:
        lines.append(f"📦 Auto-installed: {', '.join(result['packages_installed'])}")

    if result["success"]:
        lines.append(f"✅ Ran in {result['runtime']}s")
        if result["stdout"].strip():
            lines.append(f"\nOutput:\n{result['stdout']}")
        else:
            lines.append("\n(No output — add print() statements to see results)")
    else:
        lines.append(f"❌ Failed (exit {result['returncode']}) in {result['runtime']}s")
        if result["stdout"].strip():
            lines.append(f"\nStdout:\n{result['stdout']}")
        if result["stderr"].strip():
            lines.append(f"\nError:\n{result['stderr']}")
        lines.append("\nFix the error and call execute_python_code again.")

    return "\n".join(lines)
