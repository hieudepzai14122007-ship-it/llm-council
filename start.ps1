# Start Laya (:8000), the LLM Council backend (:8001) and frontend (:5173) in ONE window.
# Their output goes to logs\*.log. Press Ctrl+C to stop everything.
# (Closing the window with X leaves them running; the next start stops them first.)
$root = $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$procs = @()
$pidFile = Join-Path $logs "pids.txt"

# If the window was closed with X last time, its services are still running: stop them first
if (Test-Path $pidFile) {
    foreach ($id in Get-Content $pidFile) { taskkill /T /F /PID $id 2>$null | Out-Null }
    Remove-Item $pidFile
}

function Start-Hidden($name, $exe, $arguments, $dir) {
    $opts = @{
        FilePath = $exe; WorkingDirectory = $dir; WindowStyle = "Hidden"; PassThru = $true
        RedirectStandardOutput = (Join-Path $logs "$name.log"); RedirectStandardError = (Join-Path $logs "$name.err.log")
    }
    if ($arguments) { $opts.ArgumentList = $arguments }
    $p = Start-Process @opts
    Add-Content $pidFile $p.Id
    Write-Host "Started $name (log: logs\$name.log)"
    return $p
}

function Wait-Url($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { Start-Sleep 1 }
    }
    return $false
}

try {
    # Laya: reuse it if it's already running, otherwise start it
    if (Wait-Url "http://127.0.0.1:8000/health" 1) {
        Write-Host "Laya already running on :8000"
    } else {
        # laya-serve reads its bind address from LAYA_HOST (it ignores --host); keep it local-only
        $env:LAYA_HOST = "127.0.0.1"
        $procs += Start-Hidden "laya" "D:\laya\.venv\Scripts\laya-serve.exe" @() "D:\laya"
        Write-Host "Loading Laya models..."
        if (-not (Wait-Url "http://127.0.0.1:8000/health" 120)) {
            Write-Host "Laya did not start - questions will go to the full council. See logs\laya.err.log" -ForegroundColor Yellow
        }
    }

    # Warm up Laya's GPU so the first real question isn't slow
    $warm = '{"state":{"request":"hello"},"questions":{"q":{"type":"choice","instructions":"Which?","criteria":{"alpha":"a","beta":"b"}}}}'
    try {
        Invoke-RestMethod "http://127.0.0.1:8000/v1/systemone" -Method Post -ContentType "application/json" -Body $warm -TimeoutSec 60 | Out-Null
        Write-Host "Laya warmed up"
    } catch { }

    $procs += Start-Hidden "backend" "$root\.venv\Scripts\python.exe" "-m backend.main" $root
    $procs += Start-Hidden "frontend" "cmd.exe" "/c npm run dev" "$root\frontend"

    if (Wait-Url "http://localhost:5173" 30) { Start-Process "http://localhost:5173" }

    Write-Host ""
    Write-Host "LLM Council is running at http://localhost:5173" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop everything."
    while ($true) {
        Start-Sleep 2
        foreach ($p in $procs) {
            if ($p.HasExited) { Write-Host "A service stopped unexpectedly - check the logs folder." -ForegroundColor Red; return }
        }
    }
} finally {
    Write-Host "Stopping..."
    foreach ($p in $procs) { taskkill /T /F /PID $p.Id 2>$null | Out-Null }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
