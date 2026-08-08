# ============================================================
# naabiga-cli — installateur Windows (PowerShell)
#
# Usage :
#   iex (irm https://naabigaCode.iconedor.com/install.ps1)
#
# (iex = Invoke-Expression, irm = Invoke-RestMethod)
# ============================================================
$ErrorActionPreference = "Stop"

$Version = $env:NAABIGA_VERSION
if (-not $Version) { $Version = "v0.1.0" }
$NpmPackage = "naabiga-cli"
$GitHubRepo = "n8nprobf-hub/NaabigaCode"
$TarballUrl = "https://github.com/$GitHubRepo/releases/download/$Version/naabiga-cli-0.1.0.tgz"

function Log  { Write-Host "[naabiga] $args" -ForegroundColor Cyan }
function Warn { Write-Host "[naabiga] $args" -ForegroundColor Yellow }
function Fail { Write-Host "[naabiga] $args" -ForegroundColor Red; exit 1 }

# --- Prérequis : Node.js --------------------------------------------------
try {
    $nodeVersion = node --version
} catch {
    Fail "Node.js >= 20 est requis. Installez-le : https://nodejs.org puis relancez."
}
$nodeMajor = [int]($nodeVersion -replace "[v.]", "").Substring(0, 2)
if ($nodeMajor -lt 20) {
    Fail "Node.js >= 20 requis (trouvé : $nodeVersion)."
}
Log "Node.js $nodeVersion détecté."

# --- npm disponible ? -----------------------------------------------------
$npmAvailable = $true
try { npm --version | Out-Null } catch { $npmAvailable = $false }

if ($npmAvailable) {
    Log "Installation via npm ($NpmPackage@$($Version.TrimStart('v')))…"
    npm install -g "$NpmPackage@$($Version.TrimStart('v'))" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Log "Installé avec succès. Lancez : naabiga"
        exit 0
    }
    Warn "npm install global a échoué — fallback tarball GitHub…"
}

# --- Fallback : tarball depuis GitHub releases ---------------------------
$PrefixDir = $env:NAABIGA_PREFIX
if (-not $PrefixDir) { $PrefixDir = Join-Path $HOME ".naabiga" }

Log "Téléchargement de $TarballUrl…"
$tmpDir = Join-Path $env:TEMP "naabiga-install"
if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
New-Item -ItemType Directory -Path $tmpDir | Out-Null

try {
    Invoke-WebRequest -Uri $TarballUrl -OutFile (Join-Path $tmpDir "naabiga-cli.tgz") -UseBasicParsing
} catch {
    Fail "Téléchargement échoué. Vérifiez la version $Version sur https://github.com/$GitHubRepo/releases"
}

Log "Extraction vers $PrefixDir…"
New-Item -ItemType Directory -Path $PrefixDir -Force | Out-Null
tar -xzf (Join-Path $tmpDir "naabiga-cli.tgz") -C $tmpDir
if (Test-Path (Join-Path $tmpDir "package")) {
    Copy-Item -Recurse -Force (Join-Path $tmpDir "package\*") $PrefixDir
} else {
    Copy-Item -Recurse -Force (Join-Path $tmpDir "*") $PrefixDir
}

# --- Postinstall local (venv Python + deps) ------------------------------
Log "Préparation de l'environnement Python…"
try {
    Push-Location $PrefixDir
    node scripts/postinstall.mjs
    Pop-Location
} catch {
    Warn "Postinstall Python échoué — lancez : node $(Join-Path $PrefixDir 'scripts/postinstall.mjs')"
}

# --- PATH -----------------------------------------------------------------
$binDir = Join-Path $PrefixDir "node_modules\.bin"
if (-not (Test-Path (Join-Path $binDir "naabiga"))) {
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    New-Item -ItemType SymbolicLink -Path (Join-Path $binDir "naabiga") -Target (Join-Path $PrefixDir "bin\naabiga.mjs") -ErrorAction SilentlyContinue | Out-Null
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$binDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$binDir", "User")
    Log "PATH utilisateur mis à jour (nouveau terminal requis)."
}

Log "Installation terminée ! Lancez : naabiga"
