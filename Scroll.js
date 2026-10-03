// Scroll feel: Linear, or a macOS profile's measured scrolling at a Scrolling speed.
function copy(value) { return JSON.parse(JSON.stringify(value)) }

function fromSettings(settings) {
  if (settings.scroll_preset === "imported" && settings.imported_scroll)
    return { profile: "imported", imported: copy(settings.imported_scroll) }
  return { profile: "linear" }
}

function label(feel) {
  return feel.profile === "imported" ? "macOS · " + (feel.imported && feel.imported.name || "profile") : "Linear"
}

// The backend takes a file reference and scrolling speed, or for undo the converted scrolling itself.
function request(feel) {
  if (feel.profile !== "imported") return { profile: "linear" }
  var imported = feel.imported
  if (imported.devices) return { profile: "imported", imported: copy(imported) }
  return { profile: "imported", imported: { file: imported.file, sha256: imported.sha256, scroll_speed: imported.scroll_speed } }
}

function same(a, b) {
  if (a.profile !== b.profile) return false
  if (a.profile !== "imported") return true
  return !!a.imported && !!b.imported && a.imported.file === b.imported.file && a.imported.sha256 === b.imported.sha256
    && Math.abs(a.imported.scroll_speed - b.imported.scroll_speed) < 1e-9
}

// A profile row from `trackpads.py profiles` whose scrolling was measured and fits libinput.
function usable(row) { return !!row && !row.error && !!row.scroll && row.scroll.measured && !row.scroll.error }

// The slider's stops: Apple's scroll curves plus the Mac's own setting, which may lie between them.
function speeds(row) {
  if (!row || !row.scroll) return []
  var all = row.scroll.speeds.concat([row.scroll.speed]).sort(function(a, b) { return a - b })
  return all.filter(function(value, index) { return index === 0 || Math.abs(value - all[index - 1]) > 1e-9 })
}

function reference(row, speed) {
  return { file: row.file, sha256: row.sha256, name: row.name,
           scroll_speed: speed === undefined ? row.scroll.speed : speed }
}

if (typeof module !== "undefined") module.exports = { copy, fromSettings, label, request, same, usable, speeds, reference }
