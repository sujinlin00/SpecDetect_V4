$versionPy = Join-Path $PSScriptRoot '..\..\get_version.py'
if (Test-Path $versionPy) {
    $content = Get-Content -Path $versionPy -Raw
    if ($content -match 'ATOM_VERSION\s*=\s*"([^"]+)"') {
        $matches[1]
    } else {
        Write-Error "FATAL: Cannot parse ATOM_VERSION from $versionPy"
        exit 1
    }
} else {
    Write-Error "FATAL: get_version.py not found at $versionPy"
    exit 1
}
