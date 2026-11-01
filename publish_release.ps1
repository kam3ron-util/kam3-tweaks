param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][int]$ReleaseId,
    [Parameter(Mandatory=$true)][string]$SourceCommit,
    [Parameter(Mandatory=$true)][string]$PrivateKeyPath,
    [switch]$Upload,
    [switch]$Publish
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$python=Join-Path $root '.venv\Scripts\python.exe'
$tag="v$($Version.TrimStart('v'))"
$versionCore=$tag.TrimStart('v')
if ($versionCore -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') { throw 'Version must be a stable semantic version such as 4.7.0.' }
if ($ReleaseId -le 0) { throw 'ReleaseId must be the positive ID of the existing GitHub draft for this version.' }
if ($SourceCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'SourceCommit must be the full 40-character commit SHA.' }
$localHead = (& git -C $root rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or ([string]$localHead).Trim() -ine $SourceCommit) { throw 'The checked-out source commit does not match SourceCommit.' }
$workingChanges = @(& git -C $root status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0 -or $workingChanges.Count -gt 0) { throw 'The source checkout must be clean before release signing.' }
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI must be authenticated to verify the existing draft.' }
$releaseJson = & gh api "repos/kam3ron-util/kam3-tweaks/releases/$ReleaseId" 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Could not read the requested GitHub release draft.' }
try { $remoteRelease = ($releaseJson -join "`n") | ConvertFrom-Json } catch { throw 'GitHub returned unreadable release metadata.' }
if ([int]$remoteRelease.id -ne $ReleaseId -or $remoteRelease.tag_name -cne $tag -or -not $remoteRelease.draft) {
    throw 'The release ID must identify the unpublished draft for the requested version tag.'
}
if ([string]$remoteRelease.target_commitish -ine $SourceCommit) {
    throw 'The draft target must be updated to the exact reviewed source commit before signing.'
}
$requiredAssetNames = @('Kam3Tweaks.exe','Kam3TweaksUpdater.exe','update-manifest.json','update-manifest.sig')
$existingAssetNames = @($remoteRelease.assets | ForEach-Object { $_.name })
if (@($existingAssetNames | Where-Object { $_ -in $requiredAssetNames }).Count -gt 0) {
    throw 'The draft already has one or more release assets. Verify them or use a fresh approved draft; this script will not overwrite assets.'
}
$sourceText=Get-Content -LiteralPath (Join-Path $root 'PCBoost.py') -Raw
if ($sourceText -notmatch '(?m)^APP_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$' -or $Matches[1] -ne $versionCore) {
    throw "Requested release version $versionCore must exactly match APP_VERSION in PCBoost.py. Update the source version and metadata, test, and rebuild before preparing this release."
}
if (-not (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf)) { throw 'Encrypted private signing key file was not found.' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'update_trust.py') -PathType Leaf)) { throw 'Pinned public-key module is missing.' }
$trust=Get-Content -LiteralPath (Join-Path $root 'update_trust.py') -Raw
if ($trust -notmatch 'PINNED_PUBLIC_KEY_B64\s*=\s*"[A-Za-z0-9+/=]{40,}"') {
    throw 'No valid public signing key is pinned in update_trust.py. Configure it, rebuild and smoke-test both executables before preparing a signed release.'
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Create .venv and install requirements-build.txt first.' }
$builder=Join-Path $root 'build_windows.ps1'
& $builder
$candidateItem=Get-ChildItem -LiteralPath $root -Directory -Filter "candidate_Kam3Tweaks_${versionCore}_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $candidateItem) { throw 'Build script completed without a candidate directory.' }
$candidate=$candidateItem.FullName
$app=Join-Path $candidate 'Kam3Tweaks.exe'
$updater=Join-Path $candidate 'Kam3TweaksUpdater.exe'
foreach ($path in @($app,$updater)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Candidate release asset is missing: $path" } }
$expected="$versionCore.0"
foreach ($path in @($app,$updater)) {
    $info=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($path)
    if ($info.ProductVersion -ne $expected -or $info.FileVersion -ne $expected) { throw "Candidate metadata for $path does not match requested $versionCore." }
}
$notes=Join-Path $root 'release_notes.md'
if (-not (Test-Path -LiteralPath $notes -PathType Leaf)) { throw 'release_notes.md is missing.' }
$notesText=Get-Content -LiteralPath $notes -Raw
$notesPattern="(?ms)^# Kam3 Tweaks $([regex]::Escape($versionCore)) release notes\s*\r?\n(.*?)(?=\r?\n---\s*$|\z)"
if ($notesText -notmatch $notesPattern) { throw "release_notes.md must contain a top-level section headed '# Kam3 Tweaks $versionCore release notes'." }
$releaseNotesText="# Kam3 Tweaks $versionCore`r`n`r`n$($Matches[1].Trim())`r`n"
$releaseRoot=Join-Path $root "release_assets\Kam3Tweaks_$versionCore"
if (Test-Path -LiteralPath $releaseRoot) { throw "Refusing to overwrite existing release-preparation directory: $releaseRoot" }
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
try {
    Copy-Item -LiteralPath $app -Destination (Join-Path $releaseRoot 'Kam3Tweaks.exe')
    Copy-Item -LiteralPath $updater -Destination (Join-Path $releaseRoot 'Kam3TweaksUpdater.exe')
    Set-Content -LiteralPath (Join-Path $releaseRoot 'RELEASE_NOTES.md') -Value $releaseNotesText -Encoding utf8
    Push-Location $root
    try {
        & $python tools\release_sign.py --version $versionCore --release-id $ReleaseId `
            --exe (Join-Path $releaseRoot 'Kam3Tweaks.exe') `
            --updater (Join-Path $releaseRoot 'Kam3TweaksUpdater.exe') `
            --private-key $PrivateKeyPath --output-dir $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw "Release signing/verification failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
    $lines=@()
    foreach ($name in @('Kam3Tweaks.exe','Kam3TweaksUpdater.exe','update-manifest.json','update-manifest.sig')) {
        $path=Join-Path $releaseRoot $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Release preparation is missing $name" }
        $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines += "$hash  $name"
    }
    Set-Content -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.txt') -Value $lines -Encoding ascii
    Write-Output "Release files prepared and signature verified: $releaseRoot"
    Write-Output 'Review the four signed assets and SHA256SUMS.txt. RELEASE_NOTES.md is for the draft description and is not an upload asset.'
    Write-Output "The four release assets are Kam3Tweaks.exe, Kam3TweaksUpdater.exe, update-manifest.json, and update-manifest.sig. Never upload the private key or passphrase."
    if ($Publish) {
        $Upload = $true
        $answer=Read-Host "Type PUBLISH $tag to upload the four verified assets and publish the stable GitHub release"
        if ($answer -cne "PUBLISH $tag") { throw 'Publication canceled; no GitHub release was changed.' }
    }
    if ($Upload) {
        & gh release upload $tag (Join-Path $releaseRoot 'Kam3Tweaks.exe') (Join-Path $releaseRoot 'Kam3TweaksUpdater.exe') (Join-Path $releaseRoot 'update-manifest.json') (Join-Path $releaseRoot 'update-manifest.sig') --repo kam3ron-util/kam3-tweaks
        if ($LASTEXITCODE -ne 0) { throw 'Asset upload failed; the release remains unpublished. Inspect the draft and local files.' }
    }
    if ($Publish) {
        & gh release edit $tag --draft=false --repo kam3ron-util/kam3-tweaks
        if ($LASTEXITCODE -ne 0) { throw 'Four assets were uploaded but publication did not complete. Review the GitHub draft manually.' }
        Write-Output "Published GitHub release $tag."
    } elseif ($Upload) {
        Write-Output 'The four assets were uploaded; the release remains an unpublished draft.'
    } else {
        Write-Output 'Nothing was uploaded or published. Use -Upload only after review; -Publish additionally requires the explicit typed confirmation.'
    }
} catch {
    Write-Error $_
    throw
}
