#!/usr/bin/env bash
# ============================================================
# naabiga-cli — installateur Unix (Linux/macOS)
#
# Usage :
#   curl -fsSL https://naabigaCode.iconedor.com/install.sh | bash
#
# Installe naabiga-cli globalement via npm (ou fallback : tarball
# depuis les releases GitHub si npm n'est pas disponible/pas publié).
# ============================================================
set -euo pipefail

VERSION="${NAABIGA_VERSION:-v0.2.0}"
NPM_PACKAGE="naabiga-cli"
GITHUB_REPO="n8nprobf-hub/NaabigaCode"
TARBALL_URL="https://github.com/${GITHUB_REPO}/releases/download/${VERSION}/naabiga-cli-0.2.0.tgz"

log()  { printf '\033[1;34m[naabiga]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[naabiga]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[naabiga]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Prérequis : Node.js -------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  err "Node.js >= 20 est requis. Installez-le : https://nodejs.org (ou via nvm/fnm), puis relancez."
fi
NODE_MAJOR=$(node -e "console.log(process.versions.node.split('.')[0])")
if [ "$NODE_MAJOR" -lt 20 ]; then
  err "Node.js >= 20 requis (trouvé : $(node --version)). Mettez-le à jour puis relancez."
fi
log "Node.js $(node --version) détecté."

# --- npm disponible ? -----------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  log "Installation via npm (${NPM_PACKAGE}@${VERSION#v})…"
  if npm install -g "${NPM_PACKAGE}@${VERSION#v}" 2>/dev/null; then
    log "Installé avec succès. Lancez : naabiga"
    exit 0
  fi
  warn "npm install global a échoué (package peut-être pas encore publié) — fallback tarball GitHub…"
fi

# --- Fallback : tarball depuis GitHub releases ---------------------------
log "Téléchargement de ${TARBALL_URL}…"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if ! curl -fsSL -o "${TMP_DIR}/naabiga-cli.tgz" "${TARBALL_URL}"; then
  err "Téléchargement du tarball échoué. Vérifiez la version ${VERSION} sur https://github.com/${GITHUB_REPO}/releases"
fi

PREFIX_DIR="${NAABIGA_PREFIX:-$HOME/.naabiga}"
log "Extraction vers ${PREFIX_DIR}…"
mkdir -p "${PREFIX_DIR}"
tar -xzf "${TMP_DIR}/naabiga-cli.tgz" -C "${TMP_DIR}"
# Le tarball npm a une racine package/ ; on copie son contenu
if [ -d "${TMP_DIR}/package" ]; then
  cp -R "${TMP_DIR}/package/." "${PREFIX_DIR}/"
else
  cp -R "${TMP_DIR}/." "${PREFIX_DIR}/"
fi

# --- Postinstall local (venv Python + deps) ------------------------------
log "Préparation de l'environnement Python (venv + dépendances)…"
if command -v python3 >/dev/null 2>&1; then
  (cd "${PREFIX_DIR}" && node scripts/postinstall.mjs) || warn "Postinstall Python échoué — lancez : node ${PREFIX_DIR}/scripts/postinstall.mjs"
else
  warn "python3 introuvable — le moteur Python ne sera pas prêt. Installez Python 3 puis relancez le postinstall."
fi

# --- PATH -----------------------------------------------------------------
BIN_DIR="${PREFIX_DIR}/node_modules/.bin"
if [ ! -x "${BIN_DIR}/naabiga" ] && [ -x "${PREFIX_DIR}/bin/naabiga.mjs" ]; then
  mkdir -p "${PREFIX_DIR}/node_modules/.bin"
  ln -sf "${PREFIX_DIR}/bin/naabiga.mjs" "${BIN_DIR}/naabiga"
fi

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  SHELL_RC=""
  case "${SHELL:-}" in
    *zsh) SHELL_RC="$HOME/.zshrc" ;;
    *bash) SHELL_RC="$HOME/.bashrc" ;;
  esac
  if [ -n "$SHELL_RC" ]; then
    printf '\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$SHELL_RC"
    log "PATH ajouté dans ${SHELL_RC}"
  else
    log "Ajoutez à votre PATH : export PATH=\"${BIN_DIR}:\$PATH\""
  fi
fi

log "Installation terminée ! Lancez : naabiga"
log "  (ouvrez un nouveau terminal si la commande n'est pas trouvée)"
