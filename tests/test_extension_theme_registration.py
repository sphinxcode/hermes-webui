"""Extension theme-registration capability (window.registerHermesSkin).

Two layers:
  1. Structural — the public API + sanitizer + reserved-key guard exist in boot.js.
  2. Behavioral — a Node harness extracts the real registration/sanitization
     functions and drives them against adversarial input, proving the
     CSS-injection guard actually rejects unsafe token values (the
     security-critical contract) and that registration is additive + idempotent.

The behavioral layer is skipped (not failed) if `node` is unavailable, so the
suite never goes red purely on a missing optional toolchain.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")


# ── Layer 1: structural ──────────────────────────────────────────────────────

def test_register_api_exposed_on_window():
    assert "function registerHermesSkin(descriptor)" in BOOT_JS, (
        "registerHermesSkin API missing from boot.js"
    )
    assert "window.registerHermesSkin=registerHermesSkin" in BOOT_JS, (
        "registerHermesSkin must be exposed on window for extensions to call"
    )


def test_token_sanitizer_and_allowlist_present():
    assert "_sanitizeSkinTokens" in BOOT_JS
    assert "_ALLOWED_SKIN_TOKENS" in BOOT_JS, "token allowlist must exist"
    assert "_SAFE_SKIN_VALUE_RE" in BOOT_JS, "value safety regex must exist"


def test_reserved_core_skins_are_guarded():
    assert "_RESERVED_SKIN_KEYS" in BOOT_JS
    assert "if(_RESERVED_SKIN_KEYS.has(key)) return false" in BOOT_JS, (
        "an extension must never be able to overwrite a core skin key"
    )


# ── Layer 2: behavioral (Node harness drives the real functions) ─────────────

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

// Extract the self-contained pieces we need from boot.js without a DOM.
function grab(name, kind) {
  // crude but reliable function/const slice by brace/line matching
  const startRe = new RegExp((kind === 'fn' ? 'function ' : '') + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const i = src.search(startRe);
  if (i < 0) throw new Error('not found: ' + name);
  return i;
}

// Minimal globals the extracted code touches.
global.document = {
  getElementById: () => null,
  createElement: () => ({ appendChild(){}, set textContent(v){}, get textContent(){return '';} }),
  querySelectorAll: () => [],
  head: { appendChild(){} },
  documentElement: { dataset: {} },
};
const _store = {};
global.localStorage = {
  getItem: (k) => (k in _store ? _store[k] : null),
  setItem: (k, v) => { _store[k] = String(v); },
};
global.window = {};

// Pull the exact constants + functions out of boot.js by evaluating just the
// region from `const _EXT_SKIN_STYLE_ID` through the window assignment line.
const startMarker = "const _EXT_SKIN_STYLE_ID";
const endMarker = "window.registerHermesSkin=registerHermesSkin;";
const a = src.indexOf(startMarker);
const b = src.indexOf(endMarker);
if (a < 0 || b < 0) { console.log(JSON.stringify({error: 'markers not found'})); process.exit(0); }
let region = src.slice(a, b + endMarker.length);

// The region references _SKINS / _VALID_SKINS / _applySkin / _buildSkinPicker /
// _syncSkinPicker from the surrounding module — stub them.
const prelude = `
  const _SKINS = [{name:'Default',colors:['#FFD700','#FFBF00','#CD7F32']},
                  {name:'Ares',colors:['#FF4444','#CC3333','#992222']}];
  const _VALID_SKINS = new Set(_SKINS.map(s=>(s.value||s.name).toLowerCase()));
  function _applySkin(){}
  function _buildSkinPicker(){}
  function _syncSkinPicker(){}
`;
eval(prelude + region);
// In non-strict eval, `function registerHermesSkin` leaks into this scope.

const results = {};

// 1. valid skin registers
results.valid = registerHermesSkin({
  name: 'E-Ink', value: 'e-ink', colors: ['#000','#fff','#555'],
  tokens: { '--bg':'#ffffff', '--text':'#000000', '--accent':'#000000' }
});

// 2. unsafe token value (CSS injection attempt) is dropped → registration fails
//    because no valid tokens remain
results.injection = registerHermesSkin({
  name: 'Evil', value: 'evil',
  tokens: { '--bg': 'red;} body{display:none}', '--text': 'url(http://x/a.png)' }
});

// 3. partially-unsafe: keeps safe token, drops unsafe one
results.partial = registerHermesSkin({
  name: 'Partial', value: 'partial',
  tokens: { '--bg':'#123456', '--text':'expression(alert(1))', '--accent':'rgb(1,2,3)' }
});

// 4. cannot overwrite a reserved core skin
results.reserved = registerHermesSkin({
  name: 'Default', value: 'default', tokens: { '--bg':'#000000' }
});

// 5. unknown token name is dropped (not in allowlist) → fails (nothing valid)
results.unknownToken = registerHermesSkin({
  name: 'Unknown', value: 'unknown', tokens: { '--evil-prop':'#fff' }
});

// 6. idempotent re-register of same key returns true again
results.idempotent = registerHermesSkin({
  name: 'E-Ink', value: 'e-ink', tokens: { '--bg':'#fefefe' }
});

// 7. garbage input rejected
results.garbage = registerHermesSkin(null);
results.noTokens = registerHermesSkin({ name: 'X', value: 'x' });

console.log(JSON.stringify(results));
"""


def test_registration_and_sanitization_behavior():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available for behavioral harness")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_HARNESS)
        harness_path = f.name
    proc = subprocess.run(
        [node, harness_path, str(REPO / "static" / "boot.js")],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"harness failed: {proc.stderr or proc.stdout}"
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out.get("error") is None, f"harness error: {out.get('error')}"

    assert out["valid"] is True, "a clean skin descriptor must register"
    assert out["injection"] is False, (
        "a descriptor whose only tokens are CSS-injection attempts must be rejected"
    )
    assert out["partial"] is True, "safe tokens survive even if siblings are dropped"
    assert out["reserved"] is False, "must not overwrite a reserved core skin"
    assert out["unknownToken"] is False, "tokens outside the allowlist are dropped"
    assert out["idempotent"] is True, "re-registering an ext skin key is allowed"
    assert out["garbage"] is False, "null descriptor rejected"
    assert out["noTokens"] is False, "descriptor with no tokens rejected"
