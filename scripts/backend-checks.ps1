# Run the backend test/lint/type checks inside the running backend container.
# The production image ships runtime deps only, so the dev tools are installed
# on demand (they do not survive `docker compose up --build`).
#
#   powershell -File scripts/backend-checks.ps1            # all checks
#   powershell -File scripts/backend-checks.ps1 pytest     # just one
param([string]$Only = "all")

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

docker compose exec -T backend pip install -q pytest pytest-asyncio ruff mypy types-qrcode 2>&1 |
    Select-String -NotMatch "notice" | Out-Null

foreach ($f in "test_manager.py", "test_smoke.py", "pyproject.toml") {
    docker compose cp "$repo\backend\$f" "backend:/app/$f" | Out-Null
}

$failed = @()

if ($Only -in "all", "pytest") {
    Write-Output "===== pytest ====="
    docker compose exec -T -w /app backend python -m pytest test_manager.py test_smoke.py -q
    if (-not $?) { $failed += "pytest" }
}
if ($Only -in "all", "ruff") {
    Write-Output "===== ruff ====="
    docker compose exec -T -w /app backend python -m ruff check app
    if (-not $?) { $failed += "ruff" }
}
if ($Only -in "all", "mypy") {
    Write-Output "===== mypy --strict ====="
    docker compose exec -T -w /app backend python -m mypy --strict app
    if (-not $?) { $failed += "mypy" }
}

if ($failed) { Write-Output "`nFAILED: $($failed -join ', ')"; exit 1 }
Write-Output "`nAll backend checks passed."
