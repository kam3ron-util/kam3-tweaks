param(
    [switch]$Promote,
    [string]$CandidateDir
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$dist = Join-Path $root 'dist'
$backupDir = Join-Path $root 'backup'
$sourceText = Get-Content -LiteralPath (Join-Path $root 'PCBoost.py') -Raw
if ($sourceText -notmatch '(?m)^APP_VERSION\s*=\s*"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"\s*$') {
    throw 'PCBoost.py must define APP_VERSION as a stable semantic version before building.'
}
$versionCore = $Matches[1]
$versionSuffix = $versionCore.Replace('.', '_')
$expectedVersion = "$versionCore.0"
foreach ($metadataFile in @('version_info.txt','updater_version_info.txt')) {
    $metadataText = Get-Content -LiteralPath (Join-Path $root $metadataFile) -Raw
    if ($metadataText -notmatch [regex]::Escape("'FileVersion', '$expectedVersion'") -or
        $metadataText -notmatch [regex]::Escape("'ProductVersion', '$expectedVersion'")) {
        throw "$metadataFile must have FileVersion and ProductVersion $expectedVersion to match PCBoost.py."
    }
}
$appName = 'Kam3Tweaks.exe'
$updaterName = 'Kam3TweaksUpdater.exe'

function Test-PackagedExe([string]$Path, [string]$ExpectedFile, [string]$ExpectedOriginalName) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Executable not found: $Path" }
    $info = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    if ($info.FileVersion -ne $expectedVersion -or $info.ProductVersion -ne $expectedVersion -or
        $info.ProductName -ne 'Kam3 Tweaks' -or $info.OriginalFilename -ne $ExpectedOriginalName) {
        throw "Version or identity metadata mismatch for $Path (file=$($info.FileVersion), product=$($info.ProductVersion), name=$($info.OriginalFilename))."
    }
    Add-Type -AssemblyName System.Drawing
    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($Path)
    if ($null -eq $icon) { throw "No associated application icon found in $Path" }
    $icon.Dispose()
}

function Invoke-IsolatedSmoke([string]$Path, [string[]]$Arguments, [string]$DataRoot) {
    $oldAppData = $env:APPDATA
    $oldQt = $env:QT_QPA_PLATFORM
    $env:APPDATA = $DataRoot
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
        # These test modes are deliberately short, noninteractive command-line
        # invocations. Call the GUI-subsystem EXE directly so it inherits this
        # process's offscreen Qt environment; Start-Process's hidden shell launch
        # crashes this packaged Qt build on some Windows hosts.
        & $Path @Arguments
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw "Packaged smoke test failed with exit code $($exitCode): $Path" }
    } finally {
        $env:APPDATA = $oldAppData
        $env:QT_QPA_PLATFORM = $oldQt
    }
}

function Test-Pair([string]$Directory, [string]$SmokeRoot) {
    $app = Join-Path $Directory $appName
    $updater = Join-Path $Directory $updaterName
    Test-PackagedExe $app $appName 'Kam3Tweaks.exe'
    Test-PackagedExe $updater $updaterName 'Kam3TweaksUpdater.exe'
    Invoke-IsolatedSmoke $app @('--smoke-test',"--expected-public-key-sha256=$keyFingerprint") (Join-Path $SmokeRoot 'app')
    Invoke-IsolatedSmoke $updater @('--self-test',"--expected-public-key-sha256=$keyFingerprint") (Join-Path $SmokeRoot 'updater')
}

function Restore-Release([string]$Target, [string]$Backup, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) { return }
    $temp = Join-Path (Split-Path -Parent $Target) ("." + $Name + '.rollback-' + [guid]::NewGuid().ToString('N') + '.exe')
    $failed = Join-Path $backupDir ($Name + '_failed_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.exe')
    Copy-Item -LiteralPath $Backup -Destination $temp
    if (Test-Path -LiteralPath $Target) { [IO.File]::Replace($temp, $Target, $failed, $true) }
    else { [IO.File]::Move($temp, $Target) }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Create .venv and install requirements-build.txt first.' }
$keyFingerprint = & $python -c "import update_security; print(update_security.pinned_key_fingerprint())"
if ($LASTEXITCODE -ne 0 -or $keyFingerprint -notmatch '^[a-f0-9]{64}$') { throw 'Pinned public-key fingerprint could not be validated.' }

if (-not $Promote) {
    $env:QT_QPA_PLATFORM = 'offscreen'
    Push-Location $root
    try {
        & $python -m py_compile PCBoost.py ui_components.py network_info.py network_dns.py pcboost40.py github_updates.py update_trust.py update_security.py update_download.py update_installer.py updater_helper.py tools\setup_update_signing.py tools\verify_signing_key.py tools\release_sign.py
        if ($LASTEXITCODE -ne 0) { throw "Python compilation failed with exit code $LASTEXITCODE" }
        & $python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "Automated tests failed with exit code $LASTEXITCODE" }

        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $candidate = Join-Path $root "candidate_Kam3Tweaks_${versionCore}_$stamp"
        $work = Join-Path $root "build_Kam3Tweaks_${versionCore}_$stamp"
        New-Item -ItemType Directory -Path $candidate -Force | Out-Null
        $savedPath = $env:PATH
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem;$(Join-Path $root '.venv\Scripts')"
        try {
            & $python -m PyInstaller --noconfirm --clean --onefile --windowed --name Kam3Tweaks `
                --icon (Join-Path $root 'Kam3Tweaks.ico') --version-file (Join-Path $root 'version_info.txt') `
                --add-data "$(Join-Path $root 'Kam3Tweaks.ico');." --collect-all cryptography `
                --distpath $candidate --workpath (Join-Path $work 'app') --specpath (Join-Path $work 'app') `
                (Join-Path $root 'PCBoost.py')
            if ($LASTEXITCODE -ne 0) { throw "Kam3Tweaks.exe build failed with exit code $LASTEXITCODE" }
            & $python -m PyInstaller --noconfirm --clean --onefile --windowed --name Kam3TweaksUpdater `
                --icon (Join-Path $root 'Kam3Tweaks.ico') --version-file (Join-Path $root 'updater_version_info.txt') `
                --collect-all cryptography --distpath $candidate --workpath (Join-Path $work 'updater') `
                --specpath (Join-Path $work 'updater') (Join-Path $root 'updater_helper.py')
            if ($LASTEXITCODE -ne 0) { throw "Kam3TweaksUpdater.exe build failed with exit code $LASTEXITCODE" }
        } finally { $env:PATH = $savedPath }
        Test-Pair $candidate (Join-Path $candidate 'smoke_appdata')
        $appHash = (Get-FileHash -LiteralPath (Join-Path $candidate $appName) -Algorithm SHA256).Hash
        $updaterHash = (Get-FileHash -LiteralPath (Join-Path $candidate $updaterName) -Algorithm SHA256).Hash
        Write-Output "Candidate $versionCore app and trusted updater passed compilation, tests, version metadata, icon, and isolated smoke checks."
        Write-Output "Candidate directory: $candidate"
        Write-Output "Kam3Tweaks.exe SHA256: $appHash"
        Write-Output "Kam3TweaksUpdater.exe SHA256: $updaterHash"
        Write-Output 'The existing dist executables were not changed.'
    } finally { Pop-Location }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($CandidateDir)) { throw 'Use -Promote -CandidateDir with a candidate pair that passed all checks.' }
$candidateRoot = (Resolve-Path -LiteralPath $CandidateDir).Path
Test-Pair $candidateRoot (Join-Path $candidateRoot 'promote_smoke_appdata')

New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$releaseApp = Join-Path $dist $appName
$releaseUpdater = Join-Path $dist $updaterName
$running = @(Get-Process -Name 'Kam3Tweaks','Kam3TweaksUpdater' -ErrorAction SilentlyContinue)
$releaseAppFull = [IO.Path]::GetFullPath($releaseApp)
$releaseUpdaterFull = [IO.Path]::GetFullPath($releaseUpdater)
$matching = @($running | Where-Object {
    try { $_.Path -and (([IO.Path]::GetFullPath($_.Path) -ieq $releaseAppFull) -or ([IO.Path]::GetFullPath($_.Path) -ieq $releaseUpdaterFull)) }
    catch { $true }
})
if ($matching.Count -gt 0) { throw 'A default Kam3 Tweaks app or updater process is running. Close it normally before promotion; no process was stopped.' }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$oldVersion = if (Test-Path -LiteralPath $releaseApp) { [System.Diagnostics.FileVersionInfo]::GetVersionInfo($releaseApp).ProductVersion } else { 'none' }
$backupApp = Join-Path $backupDir "Kam3Tweaks_pre_$($oldVersion)_$stamp.exe"
$backupUpdater = Join-Path $backupDir "Kam3TweaksUpdater_pre_$($oldVersion)_$stamp.exe"
$stageApp = Join-Path $dist (".Kam3Tweaks_${versionSuffix}_$stamp.stage.exe")
$stageUpdater = Join-Path $dist (".Kam3TweaksUpdater_${versionSuffix}_$stamp.stage.exe")
Copy-Item -LiteralPath (Join-Path $candidateRoot $appName) -Destination $stageApp
Copy-Item -LiteralPath (Join-Path $candidateRoot $updaterName) -Destination $stageUpdater
$hadApp = Test-Path -LiteralPath $releaseApp
$hadUpdater = Test-Path -LiteralPath $releaseUpdater
try {
    if ($hadApp) { [IO.File]::Replace($stageApp, $releaseApp, $backupApp, $true) } else { [IO.File]::Move($stageApp, $releaseApp) }
    if ($hadUpdater) { [IO.File]::Replace($stageUpdater, $releaseUpdater, $backupUpdater, $true) } else { [IO.File]::Move($stageUpdater, $releaseUpdater) }
    Test-Pair $dist (Join-Path $root 'test_sandbox\release_460_smoke')
} catch {
    if ($hadUpdater -and (Test-Path -LiteralPath $backupUpdater)) { Restore-Release $releaseUpdater $backupUpdater 'Kam3TweaksUpdater' }
    elseif (-not $hadUpdater -and (Test-Path -LiteralPath $releaseUpdater)) { Remove-Item -LiteralPath $releaseUpdater -Force }
    if ($hadApp -and (Test-Path -LiteralPath $backupApp)) { Restore-Release $releaseApp $backupApp 'Kam3Tweaks' }
    elseif (-not $hadApp -and (Test-Path -LiteralPath $releaseApp)) { Remove-Item -LiteralPath $releaseApp -Force }
    throw "Final pair failed verification; previous executable(s) were restored and backups preserved. $($_.Exception.Message)"
}
$appHash = (Get-FileHash -LiteralPath $releaseApp -Algorithm SHA256).Hash
$updaterHash = (Get-FileHash -LiteralPath $releaseUpdater -Algorithm SHA256).Hash
Write-Output "Kam3 Tweaks release: $releaseApp"
Write-Output "Trusted updater helper: $releaseUpdater"
Write-Output "Version: $expectedVersion"
Write-Output "Kam3Tweaks.exe SHA256: $appHash"
Write-Output "Kam3TweaksUpdater.exe SHA256: $updaterHash"
if ($hadApp) { Write-Output "Previous app backup preserved: $backupApp" }
if ($hadUpdater) { Write-Output "Previous updater backup preserved: $backupUpdater" }
Write-Output 'Final pair passed version, icon, and isolated packaged smoke tests.'
